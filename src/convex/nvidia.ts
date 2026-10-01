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
 * Web RAG: the model gets two tools — `web_search` (Tavily) and `open_url`
 * (Firecrawl). If the gateway/model rejects tool definitions, we fall back to
 * a heuristic pipeline: strong search-y prompts trigger a Tavily search whose
 * sources are injected into the context, and URL-only prompts get Firecrawl
 * scrapes. Sources are returned so the UI can render citations.
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

function hasWebKeys() {
  return Boolean(process.env.TAVILY_API_KEY || process.env.FIRECRAWL_API_KEY);
}

const TOOLS = [
  {
    type: "function",
    function: {
      name: "web_search",
      description:
        "Search the public internet for current information. Returns a list of sources with title, URL and a content excerpt. Use whenever the answer depends on recent events, prices, docs, releases, or anything you are not certain about.",
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
];

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

      if (webEnabled && hasWebKeys()) {
        convo.push({
          role: "system",
          content:
            "You have web tools. Use web_search for current facts or anything uncertain, and open_url when a source needs deeper reading or the user pastes a link. After gathering sources, answer concisely and cite them inline like [1], [2] matching the order you used them. If no tool is needed, just answer.",
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
        if (webEnabled && hasWebKeys()) body.tools = TOOLS;

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
              const sources = await runTavily(String(args.query ?? ""));
              sources.forEach((s) => {
                if (collected.length < 12 && !collected.some((c) => c.url === s.url))
                  collected.push(s);
              });
              resultText = sourcesToContext(sources) || "No results found.";
            } else if (call.function.name === "open_url") {
              const page = await runFirecrawl(String(args.url ?? ""));
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

      if (webEnabled && hasWebKeys()) {
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

        if (urls.length > 0 && process.env.FIRECRAWL_API_KEY) {
          const scraped = await Promise.all(
            urls.slice(0, 2).map((u) => runFirecrawl(u).catch((e: Error) => ({
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
        } else if (urls.length === 0 && process.env.TAVILY_API_KEY && looksLikeSearchQuery(lastText)) {
          const searchSources = await runTavily(lastText).catch(() => []);
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
