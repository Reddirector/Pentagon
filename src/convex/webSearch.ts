"use node";

import type { WebSource } from "./webTools";
import { dedupeSources } from "./searchUtils";

/**
 * Grounded web search pipeline (no API key required).
 *
 * 1. Search: DuckDuckGo HTML → Tavily (if key) → Wikipedia+HN (always-on).
 *    Rate-limit/empty → one retry with backoff, then Tavily if configured.
 * 2. Read: fetch the top 3 URLs and extract the main text (readability-style
 *    strip of scripts/styles/nav/ads). We do NOT answer from snippets alone.
 * 3. Chunk: ~500 "token" chunks (chars/4 heuristic) with 75-token overlap.
 * 4. Retrieve: local lexical similarity (bag-of-words cosine) with a floor;
 *    only chunks above the floor are kept for grounding.
 */

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

const SEARCH_TOP_N = 5;
const READ_TOP_N = 3;
const CHUNK_CHARS = 2000; // ≈500 tokens at 4 chars/token
const CHUNK_OVERLAP_CHARS = 300; // ≈75 tokens
const SIMILARITY_FLOOR = 0.12;
const MAX_RETRIEVED = 6;
const CACHE_TTL_MS = 5 * 60 * 1000;

// ---------------------------------------------------------------------------
// 5-minute TTL cache keyed by the raw query
// ---------------------------------------------------------------------------

type CacheEntry = { at: number; result: GroundedSearchResult };

const searchCache = new Map<string, CacheEntry>();
const MAX_CACHE_ENTRIES = 128;

export function cacheGet(query: string): GroundedSearchResult | null {
  const key = query.trim().toLowerCase();
  const hit = searchCache.get(key);
  if (!hit) return null;
  if (Date.now() - hit.at > CACHE_TTL_MS) {
    searchCache.delete(key);
    return null;
  }
  return hit.result;
}

export function cacheSet(query: string, result: GroundedSearchResult) {
  const key = query.trim().toLowerCase();
  if (searchCache.size >= MAX_CACHE_ENTRIES) {
    const oldest = [...searchCache.entries()].sort((a, b) => a[1].at - b[1].at)[0];
    if (oldest) searchCache.delete(oldest[0]);
  }
  searchCache.set(key, { at: Date.now(), result });
}

// ---------------------------------------------------------------------------
// Page fetching + main-text extraction (trafilatura-equivalent, lightweight)
// ---------------------------------------------------------------------------

const NOISE_PATTERNS: RegExp[] = [
  /<script\b[\s\S]*?<\/script>/gi,
  /<style\b[\s\S]*?<\/style>/gi,
  /<noscript\b[\s\S]*?<\/noscript>/gi,
  /<template\b[\s\S]*?<\/template>/gi,
  /<svg\b[\s\S]*?<\/svg>/gi,
  /<form\b[\s\S]*?<\/form>/gi,
  /<nav\b[\s\S]*?<\/nav>/gi,
  /<header\b[\s\S]*?<\/header>/gi,
  /<footer\b[\s\S]*?<\/footer>/gi,
  /<aside\b[\s\S]*?<\/aside>/gi,
  /<!--[\s\S]*?-->/g,
];

export function extractMainText(html: string): string {
  let t = html;
  for (const re of NOISE_PATTERNS) t = t.replace(re, " ");

  // Prefer <article> / <main> content when present.
  const article =
    /<article\b[^>]*>([\s\S]*?)<\/article>/i.exec(t)?.[1] ??
    /<main\b[^>]*>([\s\S]*?)<\/main>/i.exec(t)?.[1];
  if (article && article.length > 600) t = article;

  // Block-level tags → newlines so paragraphs stay separated.
  t = t.replace(
    /<\/(p|div|li|h[1-6]|tr|blockquote|section|article|main|pre)>/gi,
    "\n",
  );
  t = t.replace(/<br\s*\/?>/gi, "\n");
  t = t.replace(/<[^>]+>/g, " ");

  const entities: Record<string, string> = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
    "&nbsp;": " ",
    "&mdash;": "—",
    "&ndash;": "–",
    "&hellip;": "…",
    "&rsquo;": "’",
    "&lsquo;": "‘",
    "&ldquo;": "“",
    "&rdquo;": "”",
  };
  t = t.replace(/&[a-z#0-9]+;/gi, (e) => entities[e.toLowerCase()] ?? " ");

  const lines = t
    .split("\n")
    .map((l) => l.replace(/[ \t]+/g, " ").trim())
    .filter((l) => l.length > 0);

  // Drop obvious boilerplate lines (menus, cookie banners, etc.)
  const boilerplate =
    /cookie|subscribe|sign in|log in|newsletter|advertisement|all rights reserved|privacy policy|terms of (service|use)|menu|skip to content/i;
  const kept = lines.filter((l) => {
    if (l.length < 25) return false;
    if (boilerplate.test(l)) return false;
    return true;
  });

  return kept.join("\n").slice(0, 24_000);
}

async function fetchPageText(
  url: string,
  signal: AbortSignal,
): Promise<{ title: string; text: string } | null> {
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": BROWSER_UA, Accept: "text/html,*/*" },
      redirect: "follow",
      signal,
    });
    if (!res.ok) return null;
    const ct = res.headers.get("content-type") ?? "";
    if (!/html|xml|text/.test(ct)) return null;
    const html = await res.text();
    const title =
      /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html)?.[1]?.trim() ?? url;
    const text = extractMainText(html);
    if (text.length < 200) return null;
    return { title: decodeEntities(title).slice(0, 200), text };
  } catch {
    return null;
  }
}

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;|&#x27;/g, "'")
    .replace(/&nbsp;/g, " ");
}

// ---------------------------------------------------------------------------
// Chunking (~500 tokens / 75-token overlap via 4-chars-per-token heuristic)
// ---------------------------------------------------------------------------

export type Chunk = {
  url: string;
  title: string;
  text: string;
  score: number;
};

export function chunkText(
  text: string,
  size = CHUNK_CHARS,
  overlap = CHUNK_OVERLAP_CHARS,
): string[] {
  if (text.length <= size) return [text];
  const chunks: string[] = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + size, text.length);
    if (end < text.length) {
      // Snap to a sentence/word boundary inside the last 20% of the chunk.
      const windowStart = Math.max(start + Math.floor(size * 0.8), start + 1);
      const window = text.slice(windowStart, end);
      const lastPeriod = Math.max(
        window.lastIndexOf(". "),
        window.lastIndexOf("\n"),
      );
      if (lastPeriod > 40) end = windowStart + lastPeriod + 1;
    }
    chunks.push(text.slice(start, end).trim());
    if (end >= text.length) break;
    start = end - overlap;
    if (start < 0) start = 0;
    if (start <= chunks.length * 0 && end >= text.length) break;
  }
  return chunks.filter((c) => c.length > 80);
}

// ---------------------------------------------------------------------------
// Local lexical "embeddings": bag-of-words cosine similarity
// ---------------------------------------------------------------------------

const STOPWORDS = new Set(
  ("a an and are as at be but by for from has have how i in is it its of on or " +
    "that the their there these they this to was we what when where which who " +
    "will with you your do does did not no yes about into over after before")
    .split(" "),
);

function tokenize(s: string): string[] {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s'-]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 1 && !STOPWORDS.has(w));
}

function termFreq(tokens: string[]): Map<string, number> {
  const tf = new Map<string, number>();
  for (const w of tokens) tf.set(w, (tf.get(w) ?? 0) + 1);
  return tf;
}

function cosine(a: Map<string, number>, b: Map<string, number>): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (const [, v] of a) na += v * v;
  for (const [k, v] of b) {
    nb += v * v;
    const av = a.get(k);
    if (av) dot += av * v;
  }
  if (na === 0 || nb === 0) return 0;
  return dot / Math.sqrt(na * nb);
}

export function retrieveTopChunks(
  query: string,
  chunks: Chunk[],
  k = MAX_RETRIEVED,
  floor = SIMILARITY_FLOOR,
): Chunk[] {
  const q = termFreq(tokenize(query));
  return chunks
    .map((c) => ({ ...c, score: cosine(q, termFreq(tokenize(c.text))) }))
    .filter((c) => c.score >= floor)
    .sort((a, b) => b.score - a.score)
    .slice(0, k);
}

// ---------------------------------------------------------------------------
// Search providers
// ---------------------------------------------------------------------------

function stripTags(s: string): string {
  return decodeEntities(s.replace(/<[^>]+>/g, "")).trim();
}

async function searchDuckDuckGo(
  query: string,
  signal: AbortSignal,
): Promise<WebSource[]> {
  const res = await fetch(
    `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`,
    { headers: { "User-Agent": BROWSER_UA, Accept: "text/html" }, signal },
  );
  if (!res.ok) throw new Error(`ddg_http_${res.status}`);
  const html = await res.text();
  if (/anomaly|challenge|captcha/i.test(html.slice(0, 2000))) {
    throw new Error("ddg_blocked");
  }
  const results: WebSource[] = [];
  const linkRe =
    /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
  const snippetRe = /class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;
  const snippets = [...html.matchAll(snippetRe)].map((m) => stripTags(m[1]));
  let i = 0;
  for (const m of html.matchAll(linkRe)) {
    const uddg = /[?&]uddg=([^&]+)/.exec(m[1])?.[1];
    const url = uddg
      ? decodeURIComponent(uddg)
      : m[1].startsWith("http")
        ? m[1]
        : "";
    const title = stripTags(m[2]);
    if (url && title) {
      results.push({ title, url, snippet: snippets[i] ?? "" });
    }
    i++;
    if (results.length >= SEARCH_TOP_N) break;
  }
  if (results.length === 0) throw new Error("ddg_empty");
  return results;
}

async function searchTavily(
  query: string,
  signal: AbortSignal,
): Promise<WebSource[]> {
  const apiKey = process.env.TAVILY_API_KEY;
  if (!apiKey) throw new Error("no_tavily_key");
  const res = await fetch("https://api.tavily.com/search", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query, max_results: SEARCH_TOP_N, search_depth: "basic" }),
    signal,
  });
  if (res.status === 429) throw new Error("tavily_rate_limited");
  if (!res.ok) throw new Error(`tavily_http_${res.status}`);
  const data = (await res.json()) as {
    results?: { title?: string; url?: string; content?: string }[];
  };
  const results = (data.results ?? [])
    .map((r) => ({
      title: r.title || r.url || "Untitled",
      url: r.url ?? "",
      snippet: (r.content ?? "").slice(0, 400),
    }))
    .filter((s) => s.url);
  if (results.length === 0) throw new Error("tavily_empty");
  return results;
}

async function searchWikipedia(
  query: string,
  signal: AbortSignal,
): Promise<WebSource[]> {
  const res = await fetch(
    `https://en.wikipedia.org/w/api.php?action=query&list=search` +
      `&srsearch=${encodeURIComponent(query)}&format=json&srlimit=4&origin=*`,
    { signal },
  );
  if (!res.ok) throw new Error("wiki_http");
  const data = (await res.json()) as {
    query?: { search?: { title?: string; snippet?: string }[] };
  };
  return (data.query?.search ?? [])
    .filter((r) => r.title)
    .map((r) => ({
      title: `Wikipedia: ${r.title}`,
      url: `https://en.wikipedia.org/wiki/${encodeURIComponent(
        (r.title ?? "").replace(/ /g, "_"),
      )}`,
      snippet: stripTags(r.snippet ?? ""),
    }));
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Full search chain with one retry/backoff, then Tavily, then the
 * always-on Wikipedia fallback. Order mirrors the spec: DDG → (rate-limit or
 * empty → retry once with backoff) → Tavily if key present → Wikipedia.
 */
export async function searchProviders(
  query: string,
  signal: AbortSignal,
): Promise<{ sources: WebSource[]; provider: string }> {
  // 1) DuckDuckGo with one retry + backoff
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const sources = await searchDuckDuckGo(query, signal);
      return { sources, provider: "duckduckgo" };
    } catch (err) {
      const msg = (err as Error).message;
      const retriable = /rate|limit|429|blocked|empty|http_5/.test(msg);
      if (attempt === 0 && retriable) {
        await sleep(900);
        continue;
      }
      break;
    }
  }

  // 2) Tavily (if configured)
  if (process.env.TAVILY_API_KEY) {
    try {
      const sources = await searchTavily(query, signal);
      return { sources, provider: "tavily" };
    } catch {
      // fall through
    }
  }

  // 3) Wikipedia (always-on, keyless)
  try {
    const sources = await searchWikipedia(query, signal);
    if (sources.length > 0) return { sources, provider: "wikipedia" };
  } catch {
    // fall through
  }
  return { sources: [], provider: "none" };
}

// ---------------------------------------------------------------------------
// Public entry: grounded search
// ---------------------------------------------------------------------------

export type GroundedSearchResult = {
  query: string;
  provider: string;
  sources: WebSource[];
  /** Retrieved page chunks actually used for grounding, with citations. */
  passages: {
    url: string;
    title: string;
    text: string;
    score: number;
  }[];
  pagesOpened: number;
  charsExtracted: number;
};

export async function groundedWebSearch(
  query: string,
  signal: AbortSignal,
): Promise<GroundedSearchResult> {
  const cached = cacheGet(query);
  if (cached) return { ...cached, provider: `${cached.provider} (cached)` };

  const { sources, provider } = await searchProviders(query, signal);
  if (sources.length === 0) {
    return { query, provider: "none", sources: [], passages: [], pagesOpened: 0, charsExtracted: 0 };
  }

  // Open the top 3 URLs and extract main text.
  const top = dedupeSources(sources).slice(0, READ_TOP_N);
  const pages = await Promise.all(
    top.map(async (s) => ({
      source: s,
      page: await fetchPageText(s.url, signal),
    })),
  );

  // Chunk everything we extracted.
  const allChunks: Chunk[] = [];
  let charsExtracted = 0;
  for (const { source, page } of pages) {
    if (!page) continue;
    charsExtracted += page.text.length;
    for (const c of chunkText(page.text)) {
      allChunks.push({ url: source.url, title: page.title || source.title, text: c, score: 0 });
    }
  }

  const passages = retrieveTopChunks(query, allChunks);

  const result: GroundedSearchResult = {
    query,
    provider,
    sources: top,
    passages: passages.map((p) => ({ url: p.url, title: p.title, text: p.text, score: Number(p.score.toFixed(3)) })),
    pagesOpened: pages.filter((p) => p.page).length,
    charsExtracted,
  };
  cacheSet(query, result);
  return result;
}
