// TEMPORARY DEBUG PROBES — delete after diagnosis.
// V8-runtime probes: raw fetch against NVIDIA NIM + a control host.
// Every probe is hard-bounded so the action always returns.

import { action } from "./_generated/server";

const NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions";
const CONTROL_URL = "https://api.github.com/zen";
const BOUND_MS = 25_000;

type ProbeResult = {
  name: string;
  ok: boolean;
  status: number | null;
  ms: number;
  bodyPreview: string;
  error: string | null;
};

function bounded<T>(p: Promise<T>, ms: number, label: string): Promise<T> {
  return Promise.race([
    p,
    new Promise<T>((_, reject) =>
      setTimeout(
        () => reject(new Error(`${label}: exceeded ${ms}ms bound`)),
        ms,
      ),
    ),
  ]);
}

async function timedFetch(
  name: string,
  url: string,
  init: RequestInit,
): Promise<ProbeResult> {
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BOUND_MS);
  try {
    const res = await bounded(
      fetch(url, { ...init, signal: controller.signal }),
      BOUND_MS,
      `${name} headers`,
    );
    const headersMs = Date.now() - started;
    let bodyPreview = "";
    try {
      const text = await bounded(res.text(), 10_000, `${name} body`);
      bodyPreview = text.slice(0, 240);
    } catch (e) {
      bodyPreview = `<body read failed: ${(e as Error).message}>`;
    }
    return {
      name,
      ok: res.ok,
      status: res.status,
      ms: headersMs,
      bodyPreview,
      error: null,
    };
  } catch (err) {
    return {
      name,
      ok: false,
      status: null,
      ms: Date.now() - started,
      bodyPreview: "",
      error: `${(err as Error).name}: ${(err as Error).message}`,
    };
  } finally {
    clearTimeout(timer);
  }
}

export const probeV8 = action({
  args: {},
  handler: async (): Promise<ProbeResult[]> => {
    const apiKey = process.env.NVIDIA_API_KEY;
    if (!apiKey) {
      return [
        {
          name: "config",
          ok: false,
          status: null,
          ms: 0,
          bodyPreview: "",
          error: "Missing NVIDIA_API_KEY",
        },
      ];
    }

    const control = timedFetch("control-github", CONTROL_URL, {
      headers: { "User-Agent": "neochat-debug" },
    });

    const nonstream = timedFetch("nvidia-nonstream", NVIDIA_URL, {
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

    const stream = timedFetch("nvidia-stream", NVIDIA_URL, {
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

    // For the stream probe, try to read a couple of chunks if headers arrived.
    return results;
  },
});
