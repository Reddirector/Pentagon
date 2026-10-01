import OpenAI from "openai";
import { v } from "convex/values";
import { action } from "./_generated/server";
import { getAuthUserId } from "@convex-dev/auth/server";

/**
 * Chat completion proxy for the NVIDIA NIM API (OpenAI-compatible endpoint).
 * API key is read from the environment (set NVAPI_KEY in the Keys/API keys tab).
 * Model: z-ai/glm-5.3-flash — defaults match the reference snippet:
 * temperature 0.5, top_p 1, max_tokens 1024.
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
        content: v.string(),
      }),
    ),
    temperature: v.optional(v.number()),
    topP: v.optional(v.number()),
    maxTokens: v.optional(v.number()),
  },
  handler: async (ctx, { messages, temperature, topP, maxTokens }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");

    const apiKey = process.env.NVAPI_KEY;
    if (!apiKey) {
      throw new Error(
        "Missing NVAPI_KEY. Add your NVIDIA API key in the Keys/API keys tab as NVAPI_KEY.",
      );
    }

    const client = new OpenAI({
      baseURL: "https://integrate.api.nvidia.com/v1",
      apiKey,
    });

    const completion = await client.chat.completions.create({
      model: "z-ai/glm-5.3-flash",
      messages,
      temperature: temperature ?? 0.5,
      top_p: topP ?? 1,
      max_tokens: maxTokens ?? 1024,
      stream: false,
    });

    const content = completion.choices[0]?.message?.content ?? "";
    return { content };
  },
});
