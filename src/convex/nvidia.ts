import OpenAI from "openai";
import { v } from "convex/values";
import { action } from "./_generated/server";
import { getAuthUserId } from "@convex-dev/auth/server";

/**
 * Chat completion proxy for the NVIDIA NIM API (OpenAI-compatible endpoint).
 * API key is read from the environment (set NVIDIA_API_KEY in the Keys/API keys tab).
 * Model: deepseek-ai/deepseek-v4.1-flash (vision-capable).
 * Params match the reference snippet: temperature 1, top_p 0.95, max_tokens 262144.
 * Accepts multimodal messages: content can be a plain string or an array of
 * { type: "text" } / { type: "image_url" } parts (data URLs).
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
    });

    const completion = await client.chat.completions.create({
      model: "deepseek-ai/deepseek-v4.1-flash",
      messages,
      temperature: temperature ?? 1,
      top_p: topP ?? 0.95,
      max_tokens: maxTokens ?? 262144,
      stream: false,
    });

    const content = completion.choices[0]?.message?.content ?? "";
    return { content };
  },
});
