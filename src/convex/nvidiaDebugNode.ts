// TEMPORARY DEBUG PROBES (Node runtime) — delete after diagnosis.
"use node";

import { v } from "convex/values";
import { action } from "./_generated/server";

const NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions";
const CONTROL_URL = "https://api.github.com/zen";

export const probeNode = action({
  args: {},
  returns: v.any(),
  handler: async () => {
    const apiKey = process.env.NVIDIA_API_KEY;
    if (!apiKey) {
      return { error: "Missing NVIDIA_API_KEY", results: [] };
    }

    const run = async (
      name: string,
      url: string,
      init: RequestInit,
      boundMs = 25_000,
    ) => {
      const started = Date.now();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), boundMs);
      try {
        const res = await fetch(url, { ...init, signal: controller.signal });
        const text = await res.text();
        return {
          name,
          ok: res.ok,
          status: res.status,
          ms: Date.now() - started,
          bodyPreview: text.slice(0, 240),
          error: null as string | null,
        };
      } catch (err) {
        const e = err as Error;
        return {
          name,
          ok: false,
          status: null,
          ms: Date.now() - started,
          bodyPreview: "",
          error: `${e.name}: ${e.message}`,
        };
      } finally {
        clearTimeout(timer);
      }
    };

    const control = run("control-github", CONTROL_URL, {
      headers: { "User-Agent": "neochat-debug" },
    });

    const nonstream = run("nvidia-nonstream", NVIDIA_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "z-ai/glm-5.3-flash",
        messages: [{ role: "user", content: "Say OK." }],
        max_tokens: 16,
        temperature: 1,
        top_p: 0.95,
      }),
    });

    const stream = run("nvidia-stream", NVIDIA_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        model: "z-ai/glm-5.3-flash",
        messages: [{ role: "user", content: "Say OK." }],
        max_tokens: 16,
        temperature: 1,
        top_p: 0.95,
        stream: true,
      }),
    });

    const results = await Promise.all([control, nonstream, stream]);

    // Fingerprint tests: curl-like headers; POST to non-inference path.
    const variants = await Promise.all([
      run("chat-curl-headers", NVIDIA_URL, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
          Accept: "*/*",
          "Accept-Encoding": "gzip, deflate",
          "User-Agent": "curl/8.5.0",
        },
        body: JSON.stringify({
          model: "z-ai/glm-5.3-flash",
          messages: [{ role: "user", content: "Say OK." }],
          max_tokens: 16,
        }),
      }, 12_000),
      run("POST-models-path", "https://integrate.api.nvidia.com/v1/models", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: "{}",
      }, 12_000),
    ]);

    return { error: null as string | null, results: [...results, ...variants] };
  },
});
