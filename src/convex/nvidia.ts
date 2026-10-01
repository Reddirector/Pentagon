import OpenAI from "openai";
import { v } from "convex/values";
import { action } from "./_generated/server";
import { getAuthUserId } from "@convex-dev/auth/server";

/**
 * Chat completion proxy for the NVIDIA NIM API (OpenAI-compatible endpoint).
 * API key is read from the environment (set NVIDIA_API_KEY in the Keys/API keys tab).
 * Model: z-ai/glm-5.3-flash — enabled for this NVIDIA account; supports vision
 * (image_url parts) and returns reasoning_content before the final content.
 * Params match the reference snippet: temperature 1, top_p 0.95, max_tokens 262144.
 */
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

    const apiKey = process.env.NVIDIA_API_KEY;
    if (!apiKey) {
      throw new Error(
        "Missing NVIDIA_API_KEY. Add your NVIDIA API key in the Keys/API keys tab as NVIDIA_API_KEY.",
      );
    }

    const client = new OpenAI({
      baseURL: "https://integrate.api.nvidia.com/v1",
      apiKey,
      timeout: 120_000,
      maxRetries: 1,
    });

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

    const completion = await client.chat.completions.create({
      model: "z-ai/glm-5.3-flash",
      messages: prepared,
      temperature: temperature ?? 1,
      top_p: topP ?? 0.95,
      max_tokens: maxTokens ?? 262144,
      stream: false,
    });

    const choice = completion.choices[0]?.message;
    // Reasoning models may leave `content` null and put text in reasoning_content.
    const reasoning = (choice as { reasoning_content?: string | null } | undefined)
      ?.reasoning_content;
    const content = choice?.content || reasoning || "";
    return { content };
  },
});
