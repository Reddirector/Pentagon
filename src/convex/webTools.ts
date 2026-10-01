"use node";

import { v } from "convex/values";
import { action } from "./_generated/server";

/**
 * Web RAG tools for the chat model.
 * - webSearch: Tavily (LLM-ready search results with content snippets)
 * - scrapePage: Firecrawl (full-page clean markdown, handles JS/anti-bot)
 *
 * Both are plain fetch + Bearer auth. Keys come from the environment:
 * TAVILY_API_KEY (required for search), FIRECRAWL_API_KEY (optional, scraping).
 */

export type WebSource = { title: string; url: string; snippet: string };

function clamp(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

export const webSearch = action({
  args: {
    query: v.string(),
    maxResults: v.optional(v.number()),
  },
  handler: async (_ctx, { query, maxResults }): Promise<WebSource[]> => {
    const apiKey = process.env.TAVILY_API_KEY;
    if (!apiKey) {
      throw new Error(
        "Missing TAVILY_API_KEY. Add a free key from tavily.com in the Keys/API keys tab.",
      );
    }
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
          max_results: Math.min(Math.max(maxResults ?? 5, 1), 10),
          search_depth: "basic",
          include_answer: false,
        }),
        signal: controller.signal,
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(
          `Search failed (HTTP ${res.status})${detail ? `: ${detail.slice(0, 200)}` : ""}`,
        );
      }
      const data = (await res.json()) as {
        results?: { title?: string; url?: string; content?: string }[];
      };
      return (data.results ?? [])
        .map((r) => ({
          title: r.title || r.url || "Untitled",
          url: r.url ?? "",
          snippet: clamp(r.content ?? "", 400),
        }))
        .filter((s) => s.url)
        .slice(0, 8);
    } finally {
      clearTimeout(timer);
    }
  },
});

export const scrapePage = action({
  args: { url: v.string() },
  handler: async (
    _ctx,
    { url },
  ): Promise<{ url: string; title: string; markdown: string }> => {
    if (!/^https?:\/\//i.test(url)) {
      throw new Error("Only http(s) URLs can be scraped.");
    }
    const apiKey = process.env.FIRECRAWL_API_KEY;
    if (!apiKey) {
      throw new Error(
        "Scraping needs FIRECRAWL_API_KEY (free at firecrawl.dev) — add it in the Keys/API keys tab.",
      );
    }
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
          maxAge: 172_800_000, // 48h cache
        }),
        signal: controller.signal,
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(
          `Scrape failed (HTTP ${res.status})${detail ? `: ${detail.slice(0, 200)}` : ""}`,
        );
      }
      const data = (await res.json()) as {
        success?: boolean;
        data?: {
          markdown?: string;
          metadata?: { title?: string; sourceURL?: string };
        };
      };
      const markdown = data.data?.markdown ?? "";
      if (!markdown) {
        throw new Error("Page returned no readable content.");
      }
      return {
        url: data.data?.metadata?.sourceURL ?? url,
        title: data.data?.metadata?.title || url,
        markdown: clamp(markdown, 8_000),
      };
    } finally {
      clearTimeout(timer);
    }
  },
});
