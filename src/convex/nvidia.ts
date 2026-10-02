"use node";

import { v } from "convex/values";
import { action } from "./_generated/server";
import { getAuthUserId } from "@convex-dev/auth/server";
import type { WebSource } from "./webTools";

/**
 * Agentic chat completion for the NVIDIA Build model z-ai/glm-5.3-flash.
 *
 * Routing note: NVIDIA's public `integrate` edge black-holes inference POSTs
 * from serverless egress IPs (probes verified), so requests route through the
 * platform's OpenAI-compatible gateway, which reaches the same hosted model.
 *
 * Web RAG: the model gets tools — `web_search` (Tavily when TAVILY_API_KEY is
 * set, otherwise a built-in keyless DuckDuckGo search) and `open_url`
 * (Firecrawl, only when FIRECRAWL_API_KEY is set). If the gateway/model
 * rejects tool definitions, we fall back to a heuristic pipeline: strong
 * search-y prompts trigger a search whose sources are injected into the
 * context, and URL prompts get scraped. Sources are returned so the UI can
 * render citations.
 */

const MODEL = "z-ai/glm-5.3-flash";
const MAX_TOOL_ROUNDS = 4;
const DEADLINE_MS = 110_000;

type ApiMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content: string | unknown[] | null;
  tool_calls?: {
    id: string;
    type: "function";
    function: { name: string; arguments: string };
  }[];
  tool_call_id?: string;
  name?: string;
};

type ToolLoopResult = {
  content: string;
  sources: WebSource[];
  usedToolCallPath: boolean;
};

function gatewayUrl() {
  const base = (
    process.env.VLY_INTEGRATION_BASE_URL ?? "https://integrations.vly.ai"
  ).replace(/\/$/, "");
  return `${base}/v1/chat/completions`;
}

function hasScrapeKey() {
  return Boolean(process.env.FIRECRAWL_API_KEY);
}

const TOOLS = [
  {
    type: "function",
    function: {
      name: "web_search",
      description:
        "REQUIRED for any factual, time-sensitive, or news-like question (news, prices, releases, scores, weather, 'latest', 'current', 'who is', 'what is', dates, version numbers). Searches the live internet and returns ranked sources with titles, URLs and content excerpts. Always call this BEFORE answering such questions, then cite the sources you used inline like [1], [2]. Only skip it for pure math, coding, translation, or creative writing.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "The search query, phrased like a web search.",
          },
        },
        required: ["query"],
      },
    },
  },
  ...(hasScrapeKey()
    ? [
        {
          type: "function",
          function: {
            name: "open_url",
            description:
              "Fetch the full readable content (markdown) of a web page URL. Use after web_search when a source looks promising and you need more detail, or whenever the user pastes a URL.",
            parameters: {
              type: "object",
              properties: {
                url: { type: "string", description: "The http(s) URL to read." },
              },
              required: ["url"],
            },
          },
        },
      ]
    : []),
];

/**
 * Keyless web search via DuckDuckGo's HTML endpoint. Returns parsed organic
 * results (title, url, snippet). Best-effort: empty array on any failure
 * (DDG bot-challenges some datacenter IPs).
 */
async function runDuckDuckGo(query: string): Promise<WebSource[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const res = await fetch(
      `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`,
      {
        headers: {
          // A browser-like UA keeps DDG from serving a JS-only page.
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
          Accept: "text/html",
        },
        signal: controller.signal,
      },
    );
    if (!res.ok) return [];
    const html = await res.text();
    const results: WebSource[] = [];
    const linkRe =
      /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
    const snippetRe = /class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;
    const snippets: string[] = [];
    for (const m of html.matchAll(snippetRe)) snippets.push(m[1]);
    let idx = 0;
    for (const m of html.matchAll(linkRe)) {
      const rawUrl = m[1];
      // DDG wraps results in /l/?uddg=<encoded real url>
      const uddg = /[?&]uddg=([^&]+)/.exec(rawUrl)?.[1];
      const url = uddg
        ? decodeURIComponent(uddg)
        : rawUrl.startsWith("http")
          ? rawUrl
          : `https://duckduckgo.com${rawUrl}`;
      const title = m[2]
        .replace(/<[^>]+>/g, "")
        .replace(/&amp;/g, "&")
        .replace(/&#x27;|&apos;/g, "'")
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .trim();
      const snippet = (snippets[idx] ?? "")
        .replace(/<[^>]+>/g, "")
        .replace(/&amp;/g, "&")
        .replace(/&#x27;|&apos;/g, "'")
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .trim();
      idx++;
      if (url.startsWith("http") && title) {
        results.push({ title, url, snippet: snippet.slice(0, 400) });
      }
      if (results.length >= 8) break;
    }
    return results;
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Keyless encyclopedic search via the Wikipedia API. Great for people,
 * companies, places, events, tech, science. Best-effort.
 */
async function runWikipedia(query: string): Promise<WebSource[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12_000);
  try {
    const url =
      `https://en.wikipedia.org/w/api.php?action=query&list=search` +
      `&srsearch=${encodeURIComponent(query)}&format=json&srlimit=5&origin=*`;
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) return [];
    const data = (await res.json()) as {
      query?: {
        search?: { title?: string; snippet?: string }[];
      };
    };
    return (data.query?.search ?? [])
      .filter((r) => r.title)
      .map((r) => ({
        title: `Wikipedia: ${r.title}`,
        url: `https://en.wikipedia.org/wiki/${encodeURIComponent(
          (r.title ?? "").replace(/ /g, "_"),
        )}`,
        snippet: (r.snippet ?? "")
          .replace(/<[^>]+>/g, "")
          .replace(/&amp;/g, "&")
          .replace(/&quot;/g, '"')
          .trim()
          .slice(0, 400),
      }));
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Keyless tech/news search via the Hacker News Algolia API. Surfaces recent
 * articles, releases and discussions. Best-effort.
 */
async function runHackerNews(query: string): Promise<WebSource[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12_000);
  try {
    const url =
      `https://hn.algolia.com/api/v1/search?query=${encodeURIComponent(query)}` +
      `&hitsPerPage=6&tags=story`;
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) return [];
    const data = (await res.json()) as {
      hits?: {
        title?: string;
        url?: string | null;
        objectID?: string;
        story_text?: string | null;
        points?: number;
        created_at?: string;
      }[];
    };
    return (data.hits ?? [])
      .filter((h) => h.title)
      .map((h) => ({
        title: h.title ?? "Untitled",
        url:
          h.url ||
          `https://news.ycombinator.com/item?id=${h.objectID ?? ""}`,
        snippet: [
          (h.story_text ?? "").replace(/<[^>]+>/g, " ").trim(),
          h.points !== undefined ? `${h.points} points on Hacker News` : "",
        ]
          .filter(Boolean)
          .join(" · ")
          .slice(0, 400),
      }))
      .filter((s) => s.url.startsWith("http"));
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

function dedupeSources(sources: WebSource[]): WebSource[] {
  const seen = new Set<string>();
  const out: WebSource[] = [];
  for (const s of sources) {
    const key = s.url.replace(/\/$/, "");
    if (key && !seen.has(key)) {
      seen.add(key);
      out.push(s);
    }
  }
  return out.slice(0, 8);
}

/**
 * Search with graceful degradation:
 * 1. Tavily (if TAVILY_API_KEY is set) — best quality.
 * 2. DuckDuckGo HTML — keyless, works from most egress IPs.
 * 3. Wikipedia + Hacker News — keyless APIs, always available.
 */
async function runSearch(query: string): Promise<WebSource[]> {
  if (process.env.TAVILY_API_KEY) {
    const tavily = await runTavily(query).catch(() => []);
    if (tavily.length > 0) return tavily;
  }
  const ddg = await runDuckDuckGo(query);
  if (ddg.length > 0) return ddg;
  const [wiki, hn] = await Promise.all([
    runWikipedia(query),
    runHackerNews(query),
  ]);
  return dedupeSources([...wiki, ...hn]);
}

function sourcesToContext(sources: WebSource[]) {
  return sources
    .map((s, i) => `[${i + 1}] ${s.title}\nURL: ${s.url}\n${s.snippet}`)
    .join("\n\n");
}

function looksLikeSearchQuery(text: string) {
  if (!text) return false;
  if (/https?:\/\//i.test(text)) return false;
  return /\b(what|who|when|where|why|how|which|price|cost|today|latest|recent|news|current|release|score|result|weather|stock|update|now)\b/i.test(
    text,
  );
}

async function callGateway(
  apiKey: string,
  body: unknown,
  signal: AbortSignal,
): Promise<Response> {
  return fetch(gatewayUrl(), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 16384,
      temperature: 1,
      top_p: 0.95,
      stream: true,
      ...((body as Record<string, unknown>) ?? {}),
    }),
    signal,
  });
}

/** Consume an SSE stream, returning final content and any emitted tool calls. */
async function consumeStream(
  res: Response,
): Promise<{ content: string; toolCalls: ToolCall[] }> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let content = "";
  const toolCalls = new Map<
    number,
    { id: string; name: string; args: string }
  >();

  const handlePayload = (payload: string) => {
    if (payload === "[DONE]") return;
    try {
      const chunk = JSON.parse(payload) as {
        choices?: {
          delta?: {
            content?: string | null;
            reasoning?: string | null;
            reasoning_content?: string | null;
            tool_calls?: {
              index: number;
              id?: string;
              function?: { name?: string; arguments?: string };
            }[];
          };
        }[];
      };
      const delta = chunk.choices?.[0]?.delta;
      if (!delta) return;
      if (delta.content) content += delta.content;
      for (const tc of delta.tool_calls ?? []) {
        const prev = toolCalls.get(tc.index) ?? {
          id: tc.id ?? `call_${tc.index}`,
          name: "",
          args: "",
        };
        if (tc.id) prev.id = tc.id;
        if (tc.function?.name) prev.name += tc.function.name;
        if (tc.function?.arguments) prev.args += tc.function.arguments;
        toolCalls.set(tc.index, prev);
      }
    } catch {
      // Ignore malformed chunks.
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      for (const line of event.split("\n")) {
        if (line.startsWith("data:")) handlePayload(line.slice(5).trim());
      }
    }
  }

  return {
    content,
    toolCalls: [...toolCalls.entries()]
      .sort(([a], [b]) => a - b)
      .map(([, tc]) => ({
        id: tc.id,
        type: "function" as const,
        function: { name: tc.name, arguments: tc.args || "{}" },
      })),
  };
}

type ToolCall = {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
};

/** Firecrawl when the key exists, otherwise a keyless direct fetch. */
function htmlToText(html: string) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

/** Firecrawl when the key exists, otherwise a keyless direct fetch + text extraction. */
async function runOpenUrl(
  url: string,
): Promise<{ title: string; url: string; markdown: string }> {
  if (!/^https?:\/\//i.test(url)) throw new Error("Only http(s) URLs.");
  if (hasScrapeKey()) return runFirecrawl(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": BROWSER_UA, Accept: "text/html,*/*" },
      redirect: "follow",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`Fetch failed (HTTP ${res.status}).`);
    const contentType = res.headers.get("content-type") ?? "";
    if (!/html|text|xml/.test(contentType)) {
      throw new Error(`Unsupported content type: ${contentType.split(";")[0]}`);
    }
    const html = await res.text();
    const titleMatch = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
    const text = htmlToText(html).slice(0, 8_000);
    if (!text) throw new Error("Page returned no readable content.");
    return {
      url,
      title: titleMatch ? htmlToText(titleMatch[1]).slice(0, 200) || url : url,
      markdown: text,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function runTavily(query: string): Promise<WebSource[]> {
  const apiKey = process.env.TAVILY_API_KEY;
  if (!apiKey) throw new Error("Missing TAVILY_API_KEY.");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    const res = await fetch("https://api.tavily.com/search", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query,
        max_results: 5,
        search_depth: "basic",
        include_answer: false,
      }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`Tavily search failed (HTTP ${res.status}).`);
    const data = (await res.json()) as {
      results?: { title?: string; url?: string; content?: string }[];
    };
    return (data.results ?? [])
      .map((r) => ({
        title: r.title || r.url || "Untitled",
        url: r.url ?? "",
        snippet: (r.content ?? "").slice(0, 400),
      }))
      .filter((s) => s.url);
  } finally {
    clearTimeout(timer);
  }
}

async function runFirecrawl(
  url: string,
): Promise<{ title: string; url: string; markdown: string }> {
  const apiKey = process.env.FIRECRAWL_API_KEY;
  if (!apiKey) throw new Error("Missing FIRECRAWL_API_KEY.");
  if (!/^https?:\/\//i.test(url)) throw new Error("Only http(s) URLs.");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const res = await fetch("https://api.firecrawl.dev/v2/scrape", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        url,
        formats: ["markdown"],
        maxAge: 172_800_000,
      }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`Firecrawl scrape failed (HTTP ${res.status}).`);
    const data = (await res.json()) as {
      data?: {
        markdown?: string;
        metadata?: { title?: string; sourceURL?: string };
      };
    };
    const markdown = data.data?.markdown ?? "";
    if (!markdown) throw new Error("Page returned no readable content.");
    return {
      url: data.data?.metadata?.sourceURL ?? url,
      title: data.data?.metadata?.title || url,
      markdown: markdown.slice(0, 8_000),
    };
  } finally {
    clearTimeout(timer);
  }
}

export const complete = action({
  args: {
    messages: v.array(
      v.object({
        role: v.union(
          v.literal("system"),
          v.literal("user"),
          v.literal("assistant"),
        ),
        content: v.union(v.string(), v.array(v.any())),
      }),
    ),
    temperature: v.optional(v.number()),
    topP: v.optional(v.number()),
    maxTokens: v.optional(v.number()),
    webSearch: v.optional(v.boolean()),
  },
  handler: async (ctx, { messages, temperature, topP, maxTokens, webSearch }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");

    const apiKey = process.env.VLY_INTEGRATION_KEY;
    if (!apiKey) {
      throw new Error(
        "Missing integration credentials. Contact support — the deployment is missing VLY_INTEGRATION_KEY.",
      );
    }

    const webEnabled = webSearch !== false;

    // Convert attached images (stored in Convex storage) into base64 data URLs.
    const prepared: ApiMessage[] = await Promise.all(
      messages.map(async (m) => {
        if (typeof m.content === "string") {
          return { role: m.role, content: m.content };
        }
        const parts = await Promise.all(
          m.content.map(async (part) => {
            if (part?.type === "image_url" && part.storageId) {
              const url = await ctx.storage.getUrl(part.storageId);
              if (!url) throw new Error("Attached image is no longer available.");
              const blob = await fetch(url).then((r) => {
                if (!r.ok) throw new Error("Failed to read attached image.");
                return r.blob();
              });
              const dataUrl = await new Promise<string>((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result as string);
                reader.onerror = () =>
                  reject(new Error("Failed to encode attached image."));
                reader.readAsDataURL(blob);
              });
              return { type: "image_url", image_url: { url: dataUrl } };
            }
            return part;
          }),
        );
        return { role: m.role, content: parts };
      }),
    );

    // Deadline guard shared by the whole agentic run.
    const startedAt = Date.now();
    const controller = new AbortController();
    const abortTimer = setTimeout(
      () => controller.abort(),
      DEADLINE_MS,
    );

    try {
      // ---------- Path A: model-driven tool loop ----------
      const convo: ApiMessage[] = [...prepared];
      const collected: WebSource[] = [];
      let usedToolCallPath = false;
      let unsupported = false;

      if (webEnabled) {
        convo.push({
          role: "system",
          content:
            'Web access is ENABLED. For any factual, time-sensitive, or knowledge question (news, people, companies, products, prices, weather, sports, tech, history you are unsure of) you MUST call web_search FIRST and base your answer on the results. After searching, answer concisely and cite the sources you used inline like [1], [2] — numbering must match the order of sources you used. Only answer from memory for pure math, coding help, translation, or creative writing. If search results do not cover the question, say so plainly.',
        });
      }

      for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
        if (Date.now() - startedAt > DEADLINE_MS - 5_000) break;

        const body: Record<string, unknown> = {
          messages: convo,
        };
        if (temperature !== undefined) body.temperature = temperature;
        if (topP !== undefined) body.top_p = topP;
        if (maxTokens !== undefined) body.max_tokens = maxTokens;
        if (webEnabled) body.tools = TOOLS;

        const res = await callGateway(apiKey, body, controller.signal);
        if (!res.ok || !res.body) {
          const detail = await res.text().catch(() => "");
          let message = `Model request failed (HTTP ${res.status}).`;
          try {
            const parsed = JSON.parse(detail) as {
              error?: { message?: string } | string;
            };
            if (typeof parsed.error === "string") message = parsed.error;
            else if (parsed.error?.message) message = parsed.error.message;
          } catch {
            if (detail) message = detail.slice(0, 300);
          }
          if (
            body.tools &&
            /tool|function/i.test(message) &&
            (res.status === 400 || res.status === 404 || res.status === 422)
          ) {
            // Gateway/model rejected tool definitions — drop to fallback path.
            unsupported = true;
            convo.pop(); // remove the tool-instruction system message
            break;
          }
          throw new Error(message);
        }

        usedToolCallPath = !unsupported;
        const { content, toolCalls } = await consumeStream(res);

        if (toolCalls.length === 0) {
          if (content.trim()) {
            return {
              content,
              sources: collected,
              usedToolCallPath,
            };
          }
          break;
        }

        convo.push({
          role: "assistant",
          content: content || null,
          tool_calls: toolCalls,
        });

        for (const call of toolCalls) {
          let resultText: string;
          try {
            const args = JSON.parse(call.function.arguments || "{}") as Record<
              string,
              unknown
            >;
            if (call.function.name === "web_search") {
              const sources = await runSearch(String(args.query ?? ""));
              sources.forEach((s) => {
                if (collected.length < 12 && !collected.some((c) => c.url === s.url))
                  collected.push(s);
              });
              resultText = sourcesToContext(sources) || "No results found.";
            } else if (call.function.name === "open_url") {
              const page = await runOpenUrl(String(args.url ?? ""));
              const source: WebSource = {
                title: page.title,
                url: page.url,
                snippet: page.markdown.slice(0, 400),
              };
              if (!collected.some((c) => c.url === page.url)) collected.push(source);
              resultText = `# ${page.title}\nURL: ${page.url}\n\n${page.markdown}`;
            } else {
              resultText = `Unknown tool: ${call.function.name}`;
            }
          } catch (err) {
            resultText = `Tool error: ${(err as Error).message}`;
          }
          convo.push({
            role: "tool",
            tool_call_id: call.id,
            name: call.function.name,
            content: resultText,
          });
        }

        if (!usedToolCallPath) usedToolCallPath = true;
      }

      if (usedToolCallPath && collected.length > 0) {
        // Tools ran but we ran out of rounds/incident — best-effort finish.
        if (Date.now() - startedAt < DEADLINE_MS - 5_000) {
          const res = await callGateway(
            apiKey,
            { messages: convo },
            controller.signal,
          );
          if (res.ok && res.body) {
            const { content } = await consumeStream(res);
            if (content.trim())
              return { content, sources: collected, usedToolCallPath: true };
          }
        }
        return {
          content:
            "I gathered sources but couldn't finish composing an answer in time. Please try again.",
          sources: collected,
          usedToolCallPath: true,
        };
      }

      // ---------- Path B: heuristic fallback (no tool-calling support) ----------
      let contentText = "";
      let sources: WebSource[] = [];

      if (webEnabled) {
        const lastUser = [...prepared]
          .reverse()
          .find((m) => m.role === "user");
        const lastText =
          typeof lastUser?.content === "string"
            ? lastUser.content
            : Array.isArray(lastUser?.content)
              ? (lastUser!.content as { type: string; text?: string }[])
                  .filter((p) => p.type === "text")
                  .map((p) => p.text ?? "")
                  .join(" ")
              : "";

        const urls = lastText.match(/https?:\/\/[^\s)"'>]+/g) ?? [];

        if (urls.length > 0) {
          const scraped = await Promise.all(
            urls.slice(0, 2).map((u) => runOpenUrl(u).catch((e: Error) => ({
              title: u,
              url: u,
              markdown: `Scrape failed: ${e.message}`,
            }))),
          );
          sources = scraped.map((p) => ({
            title: p.title,
            url: p.url,
            snippet: p.markdown.slice(0, 400),
          }));
          const context = scraped
            .map(
              (p) =>
                `[${p.url}]\nTITLE: ${p.title}\n\n${p.markdown}`,
            )
            .join("\n\n---\n\n");
          convo.push({
            role: "system",
            content: `The user shared link(s). Extracted page content follows; use it to answer factually.\n\n${context}`,
          });
          contentText = "";
        } else if (urls.length === 0 && looksLikeSearchQuery(lastText)) {
          const searchSources = await runSearch(lastText).catch(() => []);
          if (searchSources.length > 0) {
            sources = searchSources;
            convo.push({
              role: "system",
              content: `Live web results (newest available) for the user's question, cited as [n]:\n\n${sourcesToContext(searchSources)}\n\nAnswer using these sources and cite inline like [1]. If they don't cover the question, say so plainly.`,
            });
          }
        }
      }

      // Final streaming answer (with optional injected context).
      const finalBody: Record<string, unknown> = { messages: convo };
      if (temperature !== undefined) finalBody.temperature = temperature;
      if (topP !== undefined) finalBody.top_p = topP;
      if (maxTokens !== undefined) finalBody.max_tokens = maxTokens;
      const finalRes = await callGateway(apiKey, finalBody, controller.signal);
      if (!finalRes.ok || !finalRes.body) {
        const detail = await finalRes.text().catch(() => "");
        let message = `Model request failed (HTTP ${finalRes.status}).`;
        try {
          const parsed = JSON.parse(detail) as {
            error?: { message?: string } | string;
          };
          if (typeof parsed.error === "string") message = parsed.error;
          else if (parsed.error?.message) message = parsed.error.message;
        } catch {
          if (detail) message = detail.slice(0, 300);
        }
        throw new Error(message);
      }
      const final = await consumeStream(finalRes);
      contentText = final.content;

      const text = contentText || "";
      if (!text.trim()) {
        throw new Error(
          "The model returned an empty response. Please try sending your message again.",
        );
      }
      return { content: text, sources, usedToolCallPath: false };
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        throw new Error(
          "The model took too long to respond. Please try sending your message again.",
        );
      }
      throw err;
    } finally {
      clearTimeout(abortTimer);
    }
  },
});
