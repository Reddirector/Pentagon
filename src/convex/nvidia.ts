"use node";

import { v } from "convex/values";
import { action } from "./_generated/server";
import { getAuthUserId } from "@convex-dev/auth/server";
import type { WebSource } from "./webTools";
import {
  getCurrentTime,
  isTimeQuery,
  extractPlaceFromQuery,
  resolveTimezone,
} from "./timeTools";
import { groundedWebSearch } from "./webSearch";
import { dedupeSources, sourcesToContext } from "./searchUtils";

/**
 * Agentic chat completion for the NVIDIA Build model z-ai/glm-5.3-flash.
 *
 * Routing note: NVIDIA's public `integrate` edge black-holes inference POSTs
 * from serverless egress IPs (probes verified), so requests route through the
 * platform's OpenAI-compatible gateway, which reaches the same hosted model.
 *
 * Tools:
 * - `get_current_time` — deterministic local clock (IANA tzdb), NO web.
 *   A rule-based router also detects time/date questions ("what time is it
 *   in india") before any model call, runs the clock directly, and skips web
 *   search entirely for those turns.
 * - `web_search` — grounded pipeline: search → open top 3 pages → extract
 *   main text → chunk → lexical retrieval with similarity floor. Answers are
 *   grounded in page content, never snippets alone.
 * - `open_url` — Firecrawl scrape when FIRECRAWL_API_KEY is set.
 *
 * The current date/time is injected into the system prompt on every turn.
 */

const MODEL = "z-ai/glm-5.3-flash";
const MAX_TOOL_ROUNDS = 4;
const DEADLINE_MS = 110_000;

type ApiMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content: string | unknown[] | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  name?: string;
};

type ToolCall = {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
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
      name: "get_current_time",
      description:
        "Get the exact current local date/time for a timezone using the device clock. NO web search needed. Use for any 'what time/date/day is it' question. Pass an IANA zone like 'Asia/Kolkata' or a place like 'Tokyo'; omit for the user's local zone.",
      parameters: {
        type: "object",
        properties: {
          tz: {
            type: "string",
            description:
              "IANA timezone id (e.g. Asia/Kolkata, America/New_York) or a place name. Optional — defaults to the user's timezone.",
          },
        },
        required: [],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "web_search",
      description:
        "Search the live internet for news, releases, prices, scores, docs, or anything time-sensitive. Returns extracted page content from the top results — cite it inline like [1], [2]. Only skip for pure math, coding help, translation, or creative writing.",
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
              "Fetch the full readable content of a web page URL (e.g. one returned by web_search, or a link the user pasted).",
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

// ---------------------------------------------------------------------------
// Keyless page reader (used by open_url and the fallback path)
// ---------------------------------------------------------------------------

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

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
  const toolCalls = new Map<number, { id: string; name: string; args: string }>();

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

function looksLikeSearchQuery(text: string) {
  if (!text) return false;
  if (/https?:\/\//i.test(text)) return false;
  return /\b(what|who|when|where|why|how|which|price|cost|today|latest|recent|news|current|release|score|result|weather|stock|update)\b/i.test(
    text,
  );
}

function lastUserText(messages: ApiMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "user") continue;
    if (typeof m.content === "string") return m.content;
    if (Array.isArray(m.content)) {
      return (m.content as { type: string; text?: string }[])
        .filter((p) => p.type === "text")
        .map((p) => p.text ?? "")
        .join(" ");
    }
  }
  return "";
}

/** Format a GroundedSearchResult as the tool payload fed back to the model. */
function groundedResultToToolText(
  result: Awaited<ReturnType<typeof groundedWebSearch>>,
): string {
  if (result.passages.length === 0) {
    return (
      "NO_USABLE_CONTENT: search returned results but no usable page content " +
      "could be extracted. Respond with ONE plain sentence stating you could " +
      "not find usable content, then offer one rephrased search the user can " +
      "try. Do not apologize more than once. Do not use emojis. Never tell " +
      "the user to check Google or any other site yourself."
    );
  }
  const ctx = result.passages
    .map(
      (p, i) =>
        `[${i + 1}] ${p.title}\nURL: ${p.url}\nEXCERPT: ${p.text.slice(0, 900)}`,
    )
    .join("\n\n");
  return (
    `Live web content (extracted from ${result.pagesOpened} full pages, ` +
    `provider: ${result.provider}):\n\n${ctx}\n\n` +
    "Answer ONLY from the excerpts above. Cite the ones you use inline like [1], [2]. " +
    "If they do not fully answer the question, say so plainly in one sentence and " +
    "offer a rephrased search — never send the user to Google, never apologize " +
    "repeatedly, never use emojis."
  );
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
    userTimezone: v.optional(v.string()),
  },
  handler: async (
    ctx,
    { messages, temperature, topP, maxTokens, webSearch, userTimezone },
  ) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");

    const apiKey = process.env.VLY_INTEGRATION_KEY;
    if (!apiKey) {
      throw new Error(
        "Missing integration credentials. Contact support — the deployment is missing VLY_INTEGRATION_KEY.",
      );
    }

    const webEnabled = webSearch !== false;
    const userTz = userTimezone || "Asia/Kolkata";

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

    const query = lastUserText(prepared);

    // ---------- Rule-based time router (no LLM call, no web) ----------
    const timeQuery = isTimeQuery(query);
    let timeRouting: { tz: string; info: ReturnType<typeof getCurrentTime> } | null =
      null;
    if (timeQuery) {
      const place = extractPlaceFromQuery(query);
      const tz = place ? resolveTimezone(place) : userTz;
      timeRouting = { tz, info: getCurrentTime(tz) };
    }

    // Per-turn clock line injected into the system prompt on EVERY request.
    const nowInfo = getCurrentTime(userTz);
    const clockLine =
      `Current date/time: ${nowInfo.date} ${nowInfo.time24} ` +
      `(${nowInfo.utcOffset}) — ${nowInfo.timezone} (${nowInfo.zoneName}).`;

    // Deadline guard shared by the whole agentic run.
    const startedAt = Date.now();
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), DEADLINE_MS);

    try {
      const convo: ApiMessage[] = [...prepared];
      const collected: WebSource[] = [];
      let usedToolCallPath = false;
      let unsupported = false;

      // Inject the clock line right after the app's own system message.
      const firstSystem = convo.findIndex((m) => m.role === "system");
      const clockMsg: ApiMessage = { role: "system", content: clockLine };
      if (firstSystem === -1) convo.unshift(clockMsg);
      else convo.splice(firstSystem + 1, 0, clockMsg);

      if (timeRouting) {
        // Time question → deterministic answer path. The router already ran
        // get_current_time; skip web search and the tool loop entirely.
        const t = timeRouting.info;
        convo.push({
          role: "system",
          content:
            `The user asked about the current time/date. The device clock has ` +
            `already been read for ${t.timezone}: today is ${t.date}, local ` +
            `time is ${t.time24} (${t.time12}), UTC offset ${t.utcOffset}, ` +
            `zone "${t.zoneName}". Answer directly from this data in one or ` +
            `two sentences — do NOT call any tools, do NOT search the web. ` +
            `No emojis.`,
        });
      } else if (webEnabled) {
        convo.push({
          role: "system",
          content:
            "You have internet tools. For any factual, time-sensitive, or knowledge question " +
            "(news, people, companies, products, prices, weather, sports, tech) call " +
            "web_search FIRST and ground your answer in the returned page content, citing " +
            "sources inline like [1], [2] in the order you use them. For time/date questions " +
            "call get_current_time instead — never search the web for the current time. " +
            "Only answer from memory for pure math, coding help, translation, or creative writing. " +
            "FAILURE RULES: if search yields no usable content, say so in ONE plain sentence " +
            "and offer a rephrased search the user could try. Never apologize more than once, " +
            "never use emojis, and never tell the user to 'check Google' or visit another site.",
        });
      }

      // Effective tool set for this turn.
      const toolsForTurn = timeRouting
        ? null // deterministic path: no tools
        : webEnabled
          ? TOOLS.filter((t) => t.function.name !== "open_url" || hasScrapeKey())
          : null;

      if (!timeRouting) {
        for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
          if (Date.now() - startedAt > DEADLINE_MS - 5_000) break;

          const body: Record<string, unknown> = { messages: convo };
          if (temperature !== undefined) body.temperature = temperature;
          if (topP !== undefined) body.top_p = topP;
          if (maxTokens !== undefined) body.max_tokens = maxTokens;
          if (toolsForTurn) body.tools = toolsForTurn;

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
              // Gateway/model rejected tool definitions — drop to fallback.
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
              return { content, sources: collected, usedToolCallPath };
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
              const args = JSON.parse(
                call.function.arguments || "{}",
              ) as Record<string, unknown>;

              if (call.function.name === "get_current_time") {
                const info = getCurrentTime(
                  String(args.tz ?? userTz) || userTz,
                );
                resultText =
                  `CURRENT_TIME ${info.iso}${info.utcOffset} — ${info.weekday}, ` +
                  `${info.timezone} (${info.zoneName}). Answer using this exact ` +
                  `reading. Do not call web_search for the time.`;
              } else if (call.function.name === "web_search") {
                const grounded = await groundedWebSearch(
                  String(args.query ?? ""),
                  controller.signal,
                );
                for (const s of dedupeSources(grounded.sources)) {
                  if (
                    collected.length < 12 &&
                    !collected.some((c) => c.url === s.url)
                  ) {
                    collected.push(s);
                  }
                }
                resultText = groundedResultToToolText(grounded);
              } else if (call.function.name === "open_url") {
                const page = await runOpenUrl(String(args.url ?? ""));
                const source: WebSource = {
                  title: page.title,
                  url: page.url,
                  snippet: page.markdown.slice(0, 400),
                };
                if (!collected.some((c) => c.url === page.url))
                  collected.push(source);
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
          // Tools ran but we ran out of rounds/deadline — best-effort finish.
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
      }

      // ---------- Fallback: direct answer (no tool-calling support) ----------
      let sources: WebSource[] = [];

      if (!timeRouting && webEnabled && unsupported) {
        const text = query;
        const urls = text.match(/https?:\/\/[^\s)"'>]+/g) ?? [];

        if (urls.length === 0 && looksLikeSearchQuery(text)) {
          const grounded = await groundedWebSearch(text, controller.signal).catch(
            () => null,
          );
          if (grounded && grounded.passages.length > 0) {
            sources = dedupeSources(grounded.sources);
            convo.push({
              role: "system",
              content: `Live web content for the user's question, cited as [n]:\n\n${sourcesToContext(
                sources,
              )}\n\nExtracted passages:\n${grounded.passages
                .map(
                  (p, i) =>
                    `[${i + 1}] ${p.title}\nURL: ${p.url}\n${p.text.slice(0, 700)}`,
                )
                .join(
                  "\n\n",
                )}\n\nAnswer using these sources and cite inline like [1]. If they do not cover the question, say so plainly in one sentence and offer a rephrased search. Never apologize repeatedly, never use emojis, never tell the user to check Google.`,
            });
          } else {
            convo.push({
              role: "system",
              content:
                "No usable web content was found for this question. State that plainly in ONE sentence, then offer one rephrased search the user could try. Do not apologize more than once, do not use emojis, do not tell the user to check Google.",
            });
          }
        }
      }

      // Final streaming answer.
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

      if (!final.content.trim()) {
        throw new Error(
          "The model returned an empty response. Please try sending your message again.",
        );
      }
      return {
        content: final.content,
        sources,
        usedToolCallPath: !timeRouting && usedToolCallPath,
      };
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
