import { api } from "@/convex/_generated/api";
import type { Id } from "@/convex/_generated/dataModel";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  ArrowUp,
  Bot,
  Check,
  Copy,
  ImagePlus,
  LogOut,
  MessagesSquare,
  PanelLeft,
  Pencil,
  Plus,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useAction, useMutation, useQuery } from "convex/react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

function ChatMessageImage({ storageId }: { storageId: Id<"_storage"> }) {
  const url = useQuery(api.chats.imageUrl, { storageId });
  if (!url) return null;
  return (
    <img
      src={url}
      alt="Attached"
      className="max-h-64 w-auto max-w-full border-2 border-border bg-background object-contain"
    />
  );
}
type ChatId = Id<"chats">;
type Message = {
  _id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
};

const SUGGESTIONS = [
  "Which number is larger, 9.11 or 9.8?",
  "Explain recursion like I'm five",
  "Write a haiku about databases",
  "Give me 3 startup ideas for 2026",
];

function timeLabel(ts: number) {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Dashboard() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  const chats = useQuery(api.chats.list) ?? undefined;
  const createChat = useMutation(api.chats.create);
  const renameChat = useMutation(api.chats.rename);
  const deleteChat = useMutation(api.chats.remove);
  const addMessage = useMutation(api.chats.addMessage);
  const complete = useAction(api.nvidia.complete);

  const [selectedId, setSelectedId] = useState<ChatId | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<{
    user: string;
    assistant: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [editingId, setEditingId] = useState<ChatId | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [attached, setAttached] = useState<{
    storageId: Id<"_storage">;
    previewUrl: string;
  } | null>(null);
  const [sending, setSending] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const creatingRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const generateUploadUrl = useMutation(api.chats.generateImageUploadUrl);

  // Ensure at least one chat exists and something is selected.
  useEffect(() => {
    if (chats === undefined) return;
    if (chats.length === 0) {
      if (!creatingRef.current) {
        creatingRef.current = true;
        createChat({})
          .then((id) => setSelectedId(id))
          .finally(() => {
            creatingRef.current = false;
          });
      }
      return;
    }
    setSelectedId((cur) =>
      cur && chats.some((c) => c._id === cur) ? cur : chats[0]._id,
    );
  }, [chats, createChat]);

  const messages = useQuery(
    api.chats.listMessages,
    selectedId ? { chatId: selectedId } : "skip",
  );

  const selectedChat = chats?.find((c) => c._id === selectedId);

  // Auto-scroll to the newest message.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages?.length, pending]);

  // Elapsed-seconds ticker while waiting on a slow reasoning model.
  useEffect(() => {
    if (!pending) return;
    setElapsed(0);
    const start = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [pending]);  const send = async (text: string, storageId?: Id<"_storage">) => {
    const content = text.trim();
    if (!content || pending || sending) return;
    if (!selectedId) {
      toast.error("No chat selected yet — try again in a second.");
      return;
    }
    setInput("");
    setError(null);
    setSending(true);
    setPending({ user: content, assistant: "" });
    const isFirstExchange = (messages?.length ?? 0) === 0;
    try {
      // When an image is attached, pass its storage id; the action converts
      // the stored file into a base64 data URL server-side.
      const userContent = storageId
        ? [
            ...(content ? [{ type: "text" as const, text: content }] : []),
            { type: "image_url" as const, image_url: { storageId } },
          ]
        : content;

      const history = [
        {
          role: "system" as const,
          content:
            "You are a helpful assistant. Answer clearly and concisely.",
        },
        ...(messages ?? []).map((m) => ({
          role: m.role,
          content: m.content,
        })),
        { role: "user" as const, content: userContent },
      ];
      const { content: reply } = await complete({ messages: history });
      setPending(null);
      await addMessage({
        chatId: selectedId,
        role: "user",
        content,
        imageId: storageId,
      });
      await addMessage({
        chatId: selectedId,
        role: "assistant",
        content: reply,
      });
      if (isFirstExchange) {
        const title =
          content.length > 42 ? `${content.slice(0, 42)}…` : content;
        await renameChat({ chatId: selectedId, title });
      }
    } catch (err) {
      setPending(null);
      setError(
        err instanceof Error ? err.message : "Something went wrong. Try again.",
      );
    } finally {
      setSending(false);
    }
  };

  const submit = () => {
    const storageId = attached?.storageId;
    setAttached(null);
    send(input, storageId);
  };

  const handleAttach = async (file: File | null) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Only image attachments are supported.");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      toast.error("Image must be 8 MB or smaller.");
      return;
    }
    try {
      const uploadUrl = await generateUploadUrl({});
      const result = await fetch(uploadUrl, {
        method: "POST",
        headers: { "Content-Type": file.type },
        body: file,
      });
      const { storageId } = (await result.json()) as { storageId: Id<"_storage"> };
      setAttached({ storageId, previewUrl: URL.createObjectURL(file) });
    } catch {
      toast.error("Failed to attach image.");
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const startRename = (chat: { _id: ChatId; title: string }) => {
    setEditingId(chat._id);
    setEditingTitle(chat.title);
  };

  const commitRename = async () => {
    if (editingId && editingTitle.trim()) {
      await renameChat({
        chatId: editingId,
        title: editingTitle.trim(),
      });
    }
    setEditingId(null);
  };

  const handleSignOut = async () => {
    await signOut();
    navigate("/");
  };

  const copy = async (m: Message) => {
    await navigator.clipboard.writeText(m.content);
    setCopiedId(m._id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const sidebar = (
    <div className="flex h-full w-72 flex-col bg-secondary nb-border-r">
      <div className="flex items-center justify-between gap-2 p-4 nb-border-b">
        <div className="flex items-center gap-2">
          <div className="flex size-9 items-center justify-center bg-primary nb-border">
            <Zap className="size-5" />
          </div>
          <div>
            <p className="text-sm font-black uppercase tracking-tight leading-none">
              NeoChat
            </p>
            <p className="mt-0.5 text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
              NVIDIA NIM
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          className="md:hidden"
          onClick={() => setSidebarOpen(false)}
        >
          <X className="size-4" />
        </Button>
      </div>

      <div className="p-3">
        <Button
          className="w-full gap-2 font-bold uppercase"
          variant="secondary"
          onClick={() => {
            creatingRef.current = true;
            createChat({})
              .then((id) => setSelectedId(id))
              .finally(() => {
                creatingRef.current = false;
              });
            setSidebarOpen(false);
          }}
        >
          <Plus className="size-4" />
          New chat
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto nb-scroll px-3 pb-3">
        <p className="px-1 pb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          History
        </p>
        <div className="flex flex-col gap-1.5">
          {chats === undefined && (
            <p className="px-1 text-xs text-muted-foreground">Loading…</p>
          )}
          {chats?.length === 0 && (
            <p className="px-1 text-xs text-muted-foreground">No chats yet.</p>
          )}
          {chats?.map((chat) => (
            <div
              key={chat._id}
              className={cn(
                "group flex items-center gap-1 border-2 px-2 py-1.5",
                chat._id === selectedId
                  ? "bg-primary border-foreground"
                  : "border-transparent hover:bg-card hover:border-foreground",
              )}
            >
              {editingId === chat._id ? (
                <input
                  autoFocus
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename();
                    if (e.key === "Escape") setEditingId(null);
                  }}
                  className="w-full bg-card px-1 text-sm font-semibold outline-none nb-border"
                />
              ) : (
                <>
                  <button
                    className="flex-1 truncate text-left text-sm font-semibold"
                    onClick={() => {
                      setSelectedId(chat._id);
                      setSidebarOpen(false);
                    }}
                    title={chat.title}
                  >
                    {chat.title}
                  </button>
                  <button
                    className="opacity-0 transition group-hover:opacity-100"
                    onClick={() => startRename(chat)}
                    aria-label="Rename chat"
                  >
                    <Pencil className="size-3.5" />
                  </button>
                  <button
                    className="opacity-0 transition group-hover:opacity-100 hover:text-destructive"
                    onClick={() => {
                      deleteChat({ chatId: chat._id });
                      if (chat._id === selectedId) setSelectedId(null);
                    }}
                    aria-label="Delete chat"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 p-3 nb-border-t">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex size-8 shrink-0 items-center justify-center bg-card text-xs font-black uppercase nb-border">
            {(user?.name ?? user?.email ?? "?").slice(0, 2).toUpperCase()}
          </div>
          <p className="truncate text-xs font-semibold">
            {user?.name ?? user?.email ?? "You"}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleSignOut}
          aria-label="Sign out"
        >
          <LogOut className="size-4" />
        </Button>
      </div>
    </div>
  );

  return (
    <main className="flex h-screen overflow-hidden bg-background">
      {/* Desktop sidebar */}
      <aside className="hidden md:block">{sidebar}</aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-foreground/40"
            onClick={() => setSidebarOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 nb-shadow-lg">{sidebar}</div>
        </div>
      )}

      {/* Chat column */}
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 bg-card px-4 py-3 nb-border-b">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              variant="outline"
              size="icon-sm"
              className="md:hidden"
              onClick={() => setSidebarOpen(true)}
            >
              <PanelLeft className="size-4" />
            </Button>
            <MessagesSquare className="size-4 shrink-0" />
            <h1 className="truncate text-sm font-black uppercase tracking-tight">
              {selectedChat?.title ?? "New chat"}
            </h1>
          </div>
          <Badge variant="outline" className="font-bold uppercase nb-shadow-sm">
            GLM-5.3-Flash · Vision
          </Badge>
        </header>

        <div className="nb-grid-bg flex-1 overflow-y-auto nb-scroll">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 md:p-6">
            {messages === undefined && (
              <p className="text-sm font-semibold text-muted-foreground">
                Loading messages…
              </p>
            )}

            {messages?.length === 0 && !pending && (
              <div className="flex flex-col items-center gap-6 py-10 text-center">
                <div className="flex size-14 items-center justify-center bg-primary nb-border nb-shadow">
                  <Bot className="size-7" />
                </div>
                <div>
                  <h2 className="text-xl font-black uppercase">
                    Ask anything
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Powered by z-ai/glm-5.3-flash on NVIDIA NIM.
                  </p>
                </div>
                <div className="grid w-full gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="bg-card p-3 text-left text-sm font-medium nb-border nb-press"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages?.map((m) => (
              <div
                key={m._id}
                className={cn(
                  "flex flex-col",
                  m.role === "user" ? "items-end" : "items-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[85%] px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap nb-border",
                    m.role === "user"
                      ? "bg-secondary font-medium nb-shadow"
                      : "bg-card nb-shadow",
                  )}
                >
                  {m.imageId && <ChatMessageImage storageId={m.imageId} />}
                  {m.imageId && m.content && (
                    <div className="mt-2" />
                  )}
                  {m.content}
                </div>
                <div className="mt-1 flex items-center gap-2 px-1">
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    {m.role === "user" ? "You" : "NeoChat"} ·{" "}
                    {timeLabel(m.createdAt)}
                  </span>
                  {m.role === "assistant" && (
                    <button
                      onClick={() => copy(m)}
                      className="text-muted-foreground hover:text-foreground"
                      aria-label="Copy message"
                    >
                      {copiedId === m._id ? (
                        <Check className="size-3" />
                      ) : (
                        <Copy className="size-3" />
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}

            {/* Optimistic user bubble while awaiting the API */}
            {pending && (
              <>
                <div className="flex flex-col items-end">
                  <div className="max-w-[85%] bg-secondary px-4 py-3 text-sm font-medium leading-relaxed whitespace-pre-wrap nb-border nb-shadow">
                    {attached && (
                      <img
                        src={attached.previewUrl}
                        alt="Attached"
                        className="mb-2 max-h-64 w-auto max-w-full border-2 border-border bg-background object-contain"
                      />
                    )}
                    {pending.user}
                  </div>
                  <span className="mt-1 px-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    You
                  </span>
                </div>
                <div className="flex flex-col items-start">
                  <div className="max-w-[85%] min-w-24 bg-card px-4 py-3 text-sm leading-relaxed nb-border nb-shadow">
                    {pending.assistant ? (
                      <span className="whitespace-pre-wrap">
                        {pending.assistant}
                        <span className="nb-caret">▍</span>
                      </span>
                    ) : (
                      <span className="flex gap-1 py-1">
                        <span className="nb-dot size-2 bg-foreground" />
                        <span className="nb-dot size-2 bg-foreground" />
                        <span className="nb-dot size-2 bg-foreground" />
                      </span>
                    )}
                  </div>
                  <span className="mt-1 px-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    NeoChat is thinking{elapsed > 0 ? ` · ${elapsed}s` : ""}
                    {elapsed > 15 && " · reasoning models can take a minute"}
                  </span>
                </div>
              </>
            )}

            {error && (
              <div className="border-2 border-destructive bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive nb-shadow-sm">
                {error}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="bg-card px-4 py-4 nb-border-t">
          <div className="mx-auto w-full max-w-3xl">
            {attached && (
              <div className="mb-2 flex items-center gap-3 bg-background p-2 nb-border nb-shadow-sm">
                <img
                  src={attached.previewUrl}
                  alt="Attachment preview"
                  className="h-16 w-16 border-2 border-border object-cover"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-bold uppercase tracking-wide">
                    Image attached
                  </p>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    Will be sent to the model
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => setAttached(null)}
                  aria-label="Remove attachment"
                >
                  <X className="size-4" />
                </Button>
              </div>
            )}
            <div className="flex items-end gap-2 bg-background p-2 nb-border nb-shadow">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  void handleAttach(e.target.files?.[0] ?? null);
                  e.target.value = "";
                }}
              />
              <Button
                variant="outline"
                size="icon"
                onClick={() => fileInputRef.current?.click()}
                disabled={!!pending || !!attached}
                className="mb-0.5 shrink-0"
                aria-label="Attach image"
              >
                <ImagePlus className="size-4" />
              </Button>
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Type your message… (Enter to send, Shift+Enter for newline)"
                disabled={!!pending || sending}
                className="max-h-40 min-h-10 resize-none border-0 shadow-none focus-visible:ring-0 dark:bg-transparent"
                rows={1}
              />
              <Button
                size="icon"
                onClick={submit}
                disabled={!input.trim() || !!pending || sending}
                className="mb-0.5 shrink-0"
                aria-label="Send message"
              >
                <ArrowUp className="size-4" />
              </Button>
            </div>
            <p className="mt-2 text-center text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              z-ai/glm-5.3-flash · NVIDIA NIM · temp 1 · top_p 0.95 · max
              262144 tokens
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
