import { api } from "@/convex/_generated/api";
import type { Id } from "@/convex/_generated/dataModel";
import { useAuth } from "@/hooks/use-auth";
import SettingsDialog, {
  DEFAULT_SETTINGS,
  type ChatSettings,
} from "@/components/SettingsDialog";
import Polyhedron from "@/components/Polyhedron";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  ArrowRight,
  ArrowUp,
  Check,
  ChevronRight,
  Copy,
  FileText,
  FlaskConical,
  Globe,
  ImagePlus,
  LogOut,
  MessageSquare,
  MessagesSquare,
  PanelLeft,
  Pencil,
  Plus,
  Search,
  Settings2,
  Sparkles,
  SquareTerminal,
  Trash2,
  X,
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
      className="max-h-64 w-auto max-w-full rounded-xl border border-border object-contain"
    />
  );
}

type ChatId = Id<"chats">;
type Message = {
  _id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  sources?: { title: string; url: string; snippet: string }[];
};

function SourceList({
  sources,
}: {
  sources: NonNullable<Message["sources"]>;
}) {
  return (
    <div className="mt-3 ptg-border-t pt-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
        Sources
      </p>
      <div className="flex flex-col gap-1.5">
        {sources.map((s, i) => (
          <a
            key={`${s.url}-${i}`}
            href={s.url}
            target="_blank"
            rel="noreferrer"
            className="group flex items-start gap-2.5 rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-accent"
          >
            <span className="mt-px flex size-4 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[9px] font-semibold text-primary">
              {i + 1}
            </span>
            <span className="min-w-0">
              <span className="block truncate font-medium text-foreground/90 group-hover:underline">
                {s.title}
              </span>
              <span className="block truncate text-[10px] text-muted-foreground">
                {s.url}
              </span>
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}

const SUGGESTIONS = [
  { label: "Analyze my project code", hint: "Debugged" },
  { label: "Research latest AI models", hint: "Gptruelb" },
  { label: "Help me build something", hint: "Devoted" },
  { label: "Summarize this article", hint: "Archived" },
];

const FEATURE_CARDS = [
  {
    icon: FlaskConical,
    title: "Deep Research",
    body: "Get comprehensive insights",
    tint: "text-emerald-300 bg-emerald-500/10",
  },
  {
    icon: SquareTerminal,
    title: "Code Generation",
    body: "Build, debug, create",
    tint: "text-violet-300 bg-violet-500/10",
  },
  {
    icon: Sparkles,
    title: "Data Analysis",
    body: "Turn data into knowledge",
    tint: "text-cyan-300 bg-cyan-500/10",
  },
  {
    icon: Settings2,
    title: "Custom Agents",
    body: "Automate your workflow",
    tint: "text-amber-300 bg-amber-500/10",
  },
];

const QUICK_PROMPTS = ["Deep Research", "Code", "Analyze", "Create"];

const CAPABILITIES = [
  ["RESEARCH", "left-[8%] top-[24%]"],
  ["ANALYZE", "left-[3%] top-[45%]"],
  ["BUILD", "left-[10%] top-[66%]"],
  ["PLAN", "right-[8%] top-[24%]"],
  ["EXPLORE", "right-[3%] top-[45%]"],
  ["EXECUTE", "right-[10%] top-[66%]"],
] as const;

function timeLabel(ts: number) {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function timeAgo(ts: number) {
  const mins = Math.floor((Date.now() - ts) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const SETTINGS_KEY = "neochat-settings";

function loadSettings(): ChatSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    // Fall through to defaults.
  }
  return { ...DEFAULT_SETTINGS };
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
  const [settings, setSettings] = useState<ChatSettings>(loadSettings);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Persist settings across sessions.
  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      // Storage may be unavailable; settings just won't persist.
    }
  }, [settings]);

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
  const isHome = messages !== undefined && messages.length === 0 && !pending;

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
  }, [pending]);

  const send = async (text: string, storageId?: Id<"_storage">) => {
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

      const systemContent = [
        "You are a helpful assistant. Answer clearly and concisely.",
        settings.customInstructions.trim() || null,
      ]
        .filter(Boolean)
        .join("\n\n");

      const history = [
        { role: "system" as const, content: systemContent },
        ...(messages ?? []).map((m) => ({
          role: m.role,
          content: m.content,
        })),
        { role: "user" as const, content: userContent },
      ];
      const result = await complete({
        messages: history,
        temperature: settings.temperature,
        topP: settings.topP,
        maxTokens: settings.maxTokens,
        webSearch: settings.webSearch,
        // Browser IANA zone so the clock tool answers in the user's local
        // time; backend falls back to Asia/Kolkata when absent.
        userTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
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
        content: result.content,
        sources: result.sources.length ? result.sources : undefined,
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
    if (
      e.key === "Enter" &&
      !e.shiftKey &&
      settings.sendWithEnter
    ) {
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

  const newChat = () => {
    creatingRef.current = true;
    createChat({})
      .then((id) => setSelectedId(id))
      .finally(() => {
        creatingRef.current = false;
      });
    setSidebarOpen(false);
  };

  const sidebar = (
    <div className="flex h-full w-64 flex-col bg-sidebar ptg-border-r">
      <div className="flex items-center justify-between gap-2 px-5 py-5">
        <div className="flex items-center gap-2.5">
          <Polyhedron size={30} glow={false} />
          <span className="text-xs font-semibold uppercase tracking-[0.3em]">
            Pentagon
          </span>
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

      <div className="px-3">
        <button
          onClick={newChat}
          className="flex w-full items-center gap-3 rounded-xl bg-accent px-3 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-accent/70 ptg-focus"
        >
          <Plus className="size-4" />
          New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto ptg-scroll px-3 pb-3 pt-5">
        <p className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-[0.25em] text-muted-foreground">
          History
        </p>
        <div className="flex flex-col gap-0.5">
          {chats === undefined && (
            <p className="px-2 text-xs text-muted-foreground">Loading…</p>
          )}
          {chats?.length === 0 && (
            <p className="px-2 text-xs text-muted-foreground">No chats yet.</p>
          )}
          {chats?.map((chat) => (
            <div
              key={chat._id}
              className={cn(
                "group flex items-center gap-1 rounded-xl px-2 py-2 transition-colors",
                chat._id === selectedId
                  ? "bg-accent"
                  : "hover:bg-accent/50",
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
                  className="w-full rounded-lg bg-background px-2 py-1 text-sm font-medium outline-none ring-1 ring-ring/40"
                />
              ) : (
                <>
                  <button
                    className="flex-1 truncate text-left text-sm text-foreground/85"
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
                    <Pencil className="size-3.5 text-muted-foreground hover:text-foreground" />
                  </button>
                  <button
                    className="opacity-0 transition group-hover:opacity-100 hover:text-destructive"
                    onClick={() => {
                      deleteChat({ chatId: chat._id });
                      if (chat._id === selectedId) setSelectedId(null);
                    }}
                    aria-label="Delete chat"
                  >
                    <Trash2 className="size-3.5 text-muted-foreground" />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="p-3">
        <div className="flex items-center justify-between gap-2 rounded-2xl bg-accent/60 p-3 ptg-border">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold uppercase text-primary">
              {(user?.name ?? user?.email ?? "?").slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0 leading-tight">
              <p className="truncate text-xs font-semibold">
                {user?.name ?? user?.email ?? "You"}
              </p>
              <p className="text-[10px] text-emerald-400">● Personal</p>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setSettingsOpen(true)}
              aria-label="Open settings"
              className="text-muted-foreground hover:text-foreground"
            >
              <Settings2 className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={handleSignOut}
              aria-label="Sign out"
              className="text-muted-foreground hover:text-foreground"
            >
              <LogOut className="size-4" />
            </Button>
          </div>
        </div>
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
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setSidebarOpen(false)}
          />
          <div className="absolute inset-y-0 left-0">{sidebar}</div>
        </div>
      )}

      {/* Main column */}
      <section className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="flex items-center justify-between gap-3 px-6 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              variant="ghost"
              size="icon-sm"
              className="md:hidden"
              onClick={() => setSidebarOpen(true)}
            >
              <PanelLeft className="size-4" />
            </Button>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold tracking-tight">
                {isHome ? (
                  <>
                    {greeting()},{" "}
                    <span className="text-primary">
                      {user?.name?.split(" ")[0] ?? "friend"}
                    </span>
                  </>
                ) : (
                  (selectedChat?.title ?? "New chat")
                )}
              </h1>
              {!isHome && (
                <p className="truncate text-xs text-muted-foreground">
                  GLM-5.3-flash · streaming · web RAG{" "}
                  {settings.webSearch ? "on" : "off"}
                </p>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <Button
              variant="ghost"
              size="icon-sm"
              className="rounded-full text-muted-foreground hover:text-foreground"
              aria-label="Search chats"
              onClick={() => toast.info("Chat search is coming soon.")}
            >
              <Search className="size-4" />
            </Button>
            <button
              onClick={() => setSettingsOpen(true)}
              className="flex size-8 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold uppercase text-primary ring-1 ring-primary/30 transition hover:bg-primary/25"
              aria-label="Open settings"
            >
              {(user?.name ?? user?.email ?? "?").slice(0, 2).toUpperCase()}
            </button>
          </div>
        </header>

        {/* Content */}
        <div className="ptg-stars flex-1 overflow-y-auto ptg-scroll">
          {isHome ? (
            /* ---------- HOME HERO ---------- */
            <div className="mx-auto flex w-full max-w-5xl flex-col items-center px-4 pb-16 pt-6 md:pt-12">
              {/* Polyhedron with capability labels */}
              <div className="relative flex w-full items-center justify-center py-8">
                <Polyhedron size={140} orbits className="ptg-float" />
                {CAPABILITIES.map(([label, pos]) => (
                  <span
                    key={label}
                    className={cn(
                      "absolute hidden items-center gap-2 text-[10px] font-medium uppercase tracking-[0.3em] text-muted-foreground/70 md:flex",
                      pos,
                    )}
                  >
                    <span className="size-1 rounded-full bg-primary/60" />
                    {label}
                  </span>
                ))}
              </div>

              <div className="mt-2 flex flex-col items-center gap-2 text-center">
                <h2 className="text-3xl font-semibold uppercase tracking-[0.4em] md:text-4xl">
                  Pentagon
                </h2>
                <p className="text-[10px] font-medium uppercase tracking-[0.35em] text-muted-foreground md:text-xs">
                  Your personal AI orchestrator
                </p>
              </div>

              {/* Ask me anything */}
              <div className="mt-8 w-full max-w-xl">
                <div className="flex items-center gap-2 rounded-full bg-card/80 py-2 pl-5 pr-2 ptg-border shadow-xl shadow-black/30 backdrop-blur transition-colors focus-within:border-primary/40">
                  <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        submit();
                      }
                    }}
                    placeholder="Ask me anything..."
                    className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    disabled={!!pending || sending}
                  />
                  <Button
                    size="icon"
                    onClick={submit}
                    disabled={!input.trim() || !!pending || sending}
                    className="size-9 shrink-0 rounded-full bg-foreground text-background hover:bg-foreground/85"
                    aria-label="Send message"
                  >
                    <ArrowRight className="size-4" />
                  </Button>
                </div>

                {/* Quick capability chips */}
                <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                  {QUICK_PROMPTS.map((p) => (
                    <button
                      key={p}
                      onClick={() => send(p)}
                      disabled={!!pending || sending}
                      className="flex items-center gap-1.5 rounded-full bg-card/60 px-3.5 py-1.5 text-xs font-medium text-muted-foreground ptg-border transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
                    >
                      <Sparkles className="size-3" />
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              {/* Feature cards */}
              <div className="mt-10 grid w-full gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {FEATURE_CARDS.map((f) => (
                  <button
                    key={f.title}
                    onClick={() => setInput(f.title)}
                    className="group rounded-2xl bg-card/50 p-5 text-left ptg-border transition-colors hover:border-primary/30 hover:bg-card/80"
                  >
                    <div
                      className={`mb-4 flex size-10 items-center justify-center rounded-xl ${f.tint}`}
                    >
                      <f.icon className="size-5" />
                    </div>
                    <p className="text-sm font-semibold tracking-tight">
                      {f.title}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {f.body}
                    </p>
                  </button>
                ))}
              </div>

              {/* Suggestion cards */}
              <div className="mt-4 grid w-full gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s.label}
                    onClick={() => send(s.label)}
                    disabled={!!pending || sending}
                    className="flex flex-col gap-1 rounded-xl bg-card/30 p-4 text-left ptg-border transition-colors hover:bg-card/60 disabled:opacity-50"
                  >
                    <span className="text-xs font-medium text-foreground/85">
                      {s.label}
                    </span>
                    <span className="text-[10px] uppercase tracking-widest text-muted-foreground/70">
                      {s.hint}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* ---------- CHAT THREAD ---------- */
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 p-4 md:p-6">
              {messages === undefined && (
                <p className="text-sm text-muted-foreground">
                  Loading messages…
                </p>
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
                      "max-w-[85%] px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap",
                      m.role === "user"
                        ? "rounded-2xl rounded-br-md bg-primary/20 ptg-border border-primary/25"
                        : "rounded-2xl rounded-bl-md bg-card/80 ptg-border",
                    )}
                  >
                    {m.imageId && <ChatMessageImage storageId={m.imageId} />}
                    {m.imageId && m.content && <div className="mt-2" />}
                    {m.content}
                    {m.role === "assistant" && m.sources?.length ? (
                      <SourceList sources={m.sources} />
                    ) : null}
                  </div>
                  <div className="mt-1 flex items-center gap-2 px-1">
                    <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
                      {m.role === "user" ? "You" : "Pentagon"} ·{" "}
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
                    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary/20 px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ptg-border border-primary/25">
                      {attached && (
                        <img
                          src={attached.previewUrl}
                          alt="Attached"
                          className="mb-2 max-h-64 w-auto max-w-full rounded-xl border border-border object-contain"
                        />
                      )}
                      {pending.user}
                    </div>
                    <span className="mt-1 px-1 text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
                      You
                    </span>
                  </div>
                  <div className="flex flex-col items-start">
                    <div className="flex min-w-24 max-w-[85%] items-center rounded-2xl rounded-bl-md bg-card/80 px-4 py-3 ptg-border">
                      {pending.assistant ? (
                        <span className="whitespace-pre-wrap text-sm leading-relaxed">
                          {pending.assistant}
                          <span className="ptg-caret">▍</span>
                        </span>
                      ) : (
                        <span className="flex gap-1 py-1">
                          <span className="ptg-dot size-1.5 rounded-full bg-foreground/60" />
                          <span className="ptg-dot size-1.5 rounded-full bg-foreground/60" />
                          <span className="ptg-dot size-1.5 rounded-full bg-foreground/60" />
                        </span>
                      )}
                    </div>
                    <span className="mt-1 px-1 text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
                      Pentagon is thinking{elapsed > 0 ? ` · ${elapsed}s` : ""}
                      {elapsed > 15 && " · reasoning models can take a minute"}
                    </span>
                  </div>
                </>
              )}

              {error && (
                <div className="rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {error}
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Composer (chat view only — home has its own inline prompt bar) */}
        {!isHome && (
          <div className="px-4 pb-4">
            <div className="mx-auto w-full max-w-3xl">
              {attached && (
                <div className="mb-2 flex items-center gap-3 rounded-xl bg-card/60 p-2 ptg-border">
                  <img
                    src={attached.previewUrl}
                    alt="Attachment preview"
                    className="h-14 w-14 rounded-lg border border-border object-cover"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">
                      Image attached
                    </p>
                    <p className="text-[10px] text-muted-foreground">
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
              <div className="flex items-end gap-2 rounded-2xl bg-card/80 p-2 ptg-border shadow-xl shadow-black/20 backdrop-blur transition-colors focus-within:border-primary/40">
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
                  variant="ghost"
                  size="icon"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={!!pending || !!attached}
                  className="mb-0.5 shrink-0 rounded-full text-muted-foreground hover:text-foreground"
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
                  className="max-h-40 min-h-10 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                  rows={1}
                />
                <Button
                  size="icon"
                  onClick={submit}
                  disabled={!input.trim() || !!pending || sending}
                  className="mb-0.5 shrink-0 rounded-full bg-foreground text-background hover:bg-foreground/85"
                  aria-label="Send message"
                >
                  <ArrowUp className="size-4" />
                </Button>
              </div>
              <p className="mt-2 text-center text-[10px] tracking-wide text-muted-foreground">
                z-ai/glm-5.3-flash · NVIDIA NIM · temp {settings.temperature.toFixed(2)}{" "}
                · top_p {settings.topP.toFixed(2)} · max{" "}
                {settings.maxTokens.toLocaleString()} tokens · web RAG{" "}
                {settings.webSearch ? "on" : "off"}
              </p>
            </div>
          </div>
        )}
      </section>

      {/* Right rail (desktop, home only) */}
      {isHome && (
        <aside className="hidden w-80 shrink-0 flex-col gap-4 overflow-y-auto ptg-scroll px-4 py-4 xl:flex">
          {/* Quick access */}
          <div className="rounded-2xl bg-card/50 ptg-border p-4 backdrop-blur">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold">Quick Access</p>
              <ChevronRight className="size-4 text-muted-foreground" />
            </div>
            <div className="flex flex-col">
              {              [
                {
                  icon: MessagesSquare,
                  title: "My Chats",
                  body: `${chats?.length ?? 0} conversations`,
                  tint: "text-violet-300 bg-violet-500/10",
                  onClick: () => {},
                },
                {
                  icon: FileText,
                  title: "Knowledge Base",
                  body: "Your notes, docs and resources",
                  tint: "text-cyan-300 bg-cyan-500/10",
                  onClick: () => toast.info("Knowledge base is coming soon."),
                },
                {
                  icon: Globe,
                  title: "Web RAG",
                  body: settings.webSearch
                    ? "Search + citations enabled"
                    : "Currently disabled",
                  tint: "text-emerald-300 bg-emerald-500/10",
                  onClick: () =>
                    setSettings((s) => ({ ...s, webSearch: !s.webSearch })),
                },
                {
                  icon: Settings2,
                  title: "Settings",
                  body: "Model params, data, account",
                  tint: "text-amber-300 bg-amber-500/10",
                  onClick: () => setSettingsOpen(true),
                },
              ].map((q) => (
                <button
                  key={q.title}
                  onClick={q.onClick}
                  className="group flex items-center gap-3 rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-accent/60"
                >
                  <span
                    className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${q.tint}`}
                  >
                    <q.icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {q.title}
                    </span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {q.body}
                    </span>
                  </span>
                  <ChevronRight className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
                </button>
              ))}
            </div>
          </div>

          {/* Recent activity */}
          <div className="rounded-2xl bg-card/50 ptg-border p-4 backdrop-blur">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold">Recent Activity</p>
              <button
                className="text-[11px] font-medium text-muted-foreground hover:text-foreground"
                onClick={() => chats?.[0] && setSelectedId(chats[0]._id)}
              >
                View All
              </button>
            </div>
            <div className="flex flex-col gap-1">
              {(chats ?? []).slice(0, 5).map((chat) => (
                <button
                  key={chat._id}
                  onClick={() => setSelectedId(chat._id)}
                  className="flex items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-accent/60"
                >
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-violet-500/10 text-violet-300">
                    <MessageSquare className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium">
                      {chat.title}
                    </span>
                    <span className="block text-[10px] text-muted-foreground">
                      Updated {timeAgo(chat.updatedAt)}
                    </span>
                  </span>
                </button>
              ))}
              {chats?.length === 0 && (
                <p className="px-2 py-4 text-center text-xs text-muted-foreground">
                  No activity yet — start a chat.
                </p>
              )}
            </div>
          </div>
        </aside>
      )}

      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        settings={settings}
        onSettingsChange={setSettings}
        userName={user?.name ?? user?.email ?? "You"}
        onSignOut={handleSignOut}
        onDeletedAll={() => setSelectedId(null)}
      />
    </main>
  );
}
