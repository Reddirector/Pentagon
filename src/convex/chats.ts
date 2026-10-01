import { getAuthUserId } from "@convex-dev/auth/server";
import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/** List all chats for the signed-in user, newest first. */
export const list = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) return [];
    return await ctx.db
      .query("chats")
      .withIndex("by_user_updated", (q) => q.eq("userId", userId))
      .order("desc")
      .collect();
  },
});

/** Create a new chat owned by the signed-in user. */
export const create = mutation({
  args: { title: v.optional(v.string()) },
  handler: async (ctx, { title }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");
    const now = Date.now();
    const chatId = await ctx.db.insert("chats", {
      userId,
      title: title ?? "New chat",
      updatedAt: now,
    });
    return chatId;
  },
});

/** Rename a chat (owner only). */
export const rename = mutation({
  args: { chatId: v.id("chats"), title: v.string() },
  handler: async (ctx, { chatId, title }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");
    const chat = await ctx.db.get(chatId);
    if (!chat || chat.userId !== userId) throw new Error("Chat not found");
    await ctx.db.patch(chatId, { title });
  },
});

/** Delete a chat and all its messages (owner only). */
export const remove = mutation({
  args: { chatId: v.id("chats") },
  handler: async (ctx, { chatId }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");
    const chat = await ctx.db.get(chatId);
    if (!chat || chat.userId !== userId) throw new Error("Chat not found");
    for (const msg of await ctx.db
      .query("messages")
      .withIndex("by_chat", (q) => q.eq("chatId", chatId))
      .collect()) {
      await ctx.db.delete(msg._id);
    }
    await ctx.db.delete(chatId);
  },
});

/** List the messages of a chat (owner only), oldest first. */
export const listMessages = query({
  args: { chatId: v.id("chats") },
  handler: async (ctx, { chatId }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) return [];
    const chat = await ctx.db.get(chatId);
    if (!chat || chat.userId !== userId) return [];
    return await ctx.db
      .query("messages")
      .withIndex("by_chat", (q) => q.eq("chatId", chatId))
      .order("asc")
      .collect();
  },
});

/** Insert a single message into a chat (owner only). */
export const addMessage = mutation({
  args: {
    chatId: v.id("chats"),
    role: v.union(v.literal("user"), v.literal("assistant")),
    content: v.string(),
    imageId: v.optional(v.id("_storage")),
  },
  handler: async (ctx, { chatId, role, content, imageId }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");
    const chat = await ctx.db.get(chatId);
    if (!chat || chat.userId !== userId) throw new Error("Chat not found");
    const messageId = await ctx.db.insert("messages", {
      chatId,
      role,
      content,
      imageId,
      createdAt: Date.now(),
    });
    await ctx.db.patch(chatId, { updatedAt: Date.now() });
    return messageId;
  },
});

/** Generate a short-lived upload URL for attaching an image to a message. */
export const generateImageUploadUrl = mutation({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) throw new Error("Not signed in");
    return await ctx.storage.generateUploadUrl();
  },
});

/** Resolve a storage id into a temporary display URL (owner-checked). */
export const imageUrl = query({
  args: { storageId: v.id("_storage") },
  handler: async (ctx, { storageId }) => {
    const userId = await getAuthUserId(ctx);
    if (userId === null) return null;
    return await ctx.storage.getUrl(storageId);
  },
});
