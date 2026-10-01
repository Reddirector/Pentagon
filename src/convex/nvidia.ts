"use node";

import { v } from "convex/values";
import { action } from "./_generated/server";
import { getAuthUserId } from "@convex-dev/auth/server";

/**
 * Chat completion proxy for the NVIDIA Build model z-ai/glm-5.3-flash.
 *
 * Why not the OpenAI SDK / integrate.api.nvidia.com directly?
 * NVIDIA's public `integrate` edge silently black-holes POST /v1/chat/completions
 * from serverless egress IPs (GET /v1/models responds fine, inference never
 * returns headers — verified by probes from Convex's own runtimes). Requests
 * therefore route through the platform's OpenAI-compatible integration gateway,
 * which reaches the same NVIDIA-hosted model reliably (verified 200 + SSE).
 *
 * Uses raw fetch + manual SSE parsing (no SDK) and streaming so a slow
 * reasoning model can't kill the connection; partial output is preserved on
 * stream errors or deadline overrun.
 */

const MODEL = "z-ai/glm-5.3-flash";

function gatewayUrl() {
  const base = (
    process.env.VLY_INTEGRATION_BASE_URL ?? "https://integrations.vly.ai"
  ).replace(/\/$/, "");
  return `${base}/v1/chat/completions`;
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
  },
  handler: async (ctx, { messages, temperature, topP, maxTokens }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");

    const apiKey = process.env.VLY_INTEGRATION_KEY;
    if (!apiKey) {
      throw new Error(
        "Missing integration credentials. Contact support — the deployment is missing VLY_INTEGRATION_KEY.",
      );
    }

    // Convert any attached images (stored in Convex storage) into base64 data
    // URLs so the model receives the multimodal format it expects.
    const prepared = await Promise.all(
      messages.map(async (m) => {
        if (typeof m.content === "string") return m;
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
        return { ...m, content: parts };
      }),
    );

    const started = Date.now();
    // Hard cap: reasoning models may think for a long time. Keep the action
    // from running away; whatever streamed so far is returned.
    const DEADLINE_MS = 110_000;
    let timedOut = false;

    const controller = new AbortController();
    const abortTimer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, DEADLINE_MS);

    try {
      const res = await fetch(gatewayUrl(), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          model: MODEL,
          messages: prepared,
          temperature: temperature ?? 1,
          top_p: topP ?? 0.95,
          max_tokens: maxTokens ?? 16384,
          stream: true,
        }),
        signal: controller.signal,
      });

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
        throw new Error(message);
      }

      // Manual SSE parsing: accumulate content + reasoning deltas.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let content = "";
      let reasoning = "";

      const handleChunk = (payload: string) => {
        if (payload === "[DONE]") return;
        try {
          const chunk = JSON.parse(payload) as {
            choices?: {
              delta?: {
                content?: string | null;
                reasoning?: string | null;
                reasoning_content?: string | null;
              };
            }[];
          };
          const delta = chunk.choices?.[0]?.delta;
          if (!delta) return;
          if (delta.content) content += delta.content;
          const think = delta.reasoning ?? delta.reasoning_content;
          if (think) reasoning += think;
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
            if (line.startsWith("data:")) handleChunk(line.slice(5).trim());
          }
        }
        if (Date.now() - started > DEADLINE_MS) {
          timedOut = true;
          break;
        }
      }

      const text = content || reasoning || "";
      if (!text) {
        throw new Error(
          "The model returned an empty response. Please try sending your message again.",
        );
      }
      if (timedOut && content) {
        return {
          content: `${text}\n\n_(Response truncated — the model hit the time limit. Ask again to continue.)_`,
        };
      }
      return { content: text };
    } catch (err) {
      // Distinguish user-facing aborts from unexpected failures.
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
