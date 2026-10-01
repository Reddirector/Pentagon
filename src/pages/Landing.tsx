import { motion } from "framer-motion";
import {
  ArrowRight,
  Database,
  Globe,
  Lock,
  MessagesSquare,
  Sparkles,
} from "lucide-react";
import { Link } from "react-router";
import Polyhedron from "@/components/Polyhedron";
import { Button } from "@/components/ui/button";

const FEATURES = [
  {
    icon: MessagesSquare,
    title: "Intelligent chat",
    body: "A minimal workspace with history, search, and streaming reasoning — nothing you don't need.",
    tint: "text-violet-300 bg-violet-500/10",
  },
  {
    icon: Sparkles,
    title: "GLM-5.3-flash engine",
    body: "Vision + reasoning on NVIDIA NIM via an OpenAI-compatible endpoint, streamed token by token.",
    tint: "text-cyan-300 bg-cyan-500/10",
  },
  {
    icon: Globe,
    title: "Live web RAG",
    body: "Tavily search and Firecrawl scraping give the model current sources — cited under every answer.",
    tint: "text-emerald-300 bg-emerald-500/10",
  },
  {
    icon: Database,
    title: "Persistent memory",
    body: "Every conversation is stored in Convex, so your history survives reloads and exports cleanly.",
    tint: "text-amber-300 bg-amber-500/10",
  },
  {
    icon: Lock,
    title: "Locked down",
    body: "API keys stay server-side in Convex actions. Chats belong to you alone.",
    tint: "text-rose-300 bg-rose-500/10",
  },
];

const CAPABILITIES = ["RESEARCH", "ANALYZE", "PLAN", "EXPLORE", "BUILD", "EXECUTE"];

export default function Landing() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Nav */}
      <header className="sticky top-0 z-40 bg-background/70 ptg-border-b backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-3">
            <Polyhedron size={30} glow={false} />
            <span className="text-sm font-semibold uppercase tracking-[0.35em]">
              Pentagon
            </span>
          </Link>
          <nav className="flex items-center gap-2">
            <Link to="/auth">
              <Button
                variant="ghost"
                className="rounded-full text-sm font-medium text-muted-foreground hover:text-foreground"
              >
                Sign in
              </Button>
            </Link>
            <Link to="/dashboard">
              <Button className="rounded-full bg-foreground font-medium text-background hover:bg-foreground/90">
                Launch app
                <ArrowRight className="size-4" />
              </Button>
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="ptg-stars relative overflow-hidden">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-8 px-4 py-24 text-center md:py-32">
          <Polyhedron size={150} orbits className="ptg-float" />

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="flex flex-col items-center gap-3"
          >
            <h1 className="text-5xl font-semibold uppercase tracking-[0.45em] md:text-6xl md:tracking-[0.5em]">
              Pentagon
            </h1>
            <p className="text-[11px] font-medium uppercase tracking-[0.4em] text-muted-foreground md:text-xs">
              Your personal AI orchestrator
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2 text-[10px] font-medium uppercase tracking-[0.3em] text-muted-foreground/80"
          >
            {CAPABILITIES.map((c, i) => (
              <span key={c} className="flex items-center gap-8">
                <span className="flex items-center gap-2">
                  <span className="size-1 rounded-full bg-primary/70" />
                  {c}
                </span>
                {i < CAPABILITIES.length - 1 && (
                  <span className="hidden h-px w-6 bg-border md:block" />
                )}
              </span>
            ))}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="flex max-w-xl flex-col items-center gap-3"
          >
            <p className="text-balance text-sm font-normal leading-relaxed text-muted-foreground md:text-base">
              Pentagon runs{" "}
              <span className="rounded-full bg-primary/10 px-2 py-0.5 font-semibold text-primary">
                z-ai/glm-5.3-flash
              </span>{" "}
              on NVIDIA NIM — OpenAI-compatible calls with vision and live web
              search, stored in your own encrypted Convex history.
            </p>
            <div className="mt-3 flex flex-col items-center gap-3 sm:flex-row">
              <Link to="/auth">
                <Button
                  size="lg"
                  className="rounded-full bg-primary font-medium text-primary-foreground hover:bg-primary/90"
                >
                  Start chatting
                  <ArrowRight className="size-4" />
                </Button>
              </Link>
              <Link to="/dashboard">
                <Button
                  size="lg"
                  variant="outline"
                  className="rounded-full border-border bg-transparent font-medium hover:bg-accent"
                >
                  Try the demo
                </Button>
              </Link>
            </div>
          </motion.div>

          {/* Chat preview card */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="mt-10 w-full max-w-2xl"
          >
            <div className="rounded-2xl bg-card/60 ptg-border shadow-2xl shadow-black/40 backdrop-blur-xl">
              <div className="flex items-center justify-between gap-2 rounded-t-2xl px-5 py-3 ptg-border-b">
                <div className="flex items-center gap-2">
                  <span className="size-2 rounded-full bg-emerald-400/80" />
                  <p className="text-xs font-medium tracking-wide text-muted-foreground">
                    pentagon — live
                  </p>
                </div>
                <p className="text-xs font-medium text-muted-foreground/70">
                  glm-5.3-flash
                </p>
              </div>
              <div className="flex flex-col gap-4 p-5 text-left md:p-6">
                <div className="max-w-[80%] self-end rounded-2xl rounded-br-md bg-primary/20 px-4 py-3 text-sm text-foreground/90 ptg-border border-primary/20">
                  Which number is larger, 9.11 or 9.8?
                </div>
                <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-secondary/70 px-4 py-3 text-sm leading-relaxed text-foreground/90 ptg-border">
                  9.8 is larger. Compare the first decimal digit: 9.8 = 9.80
                  and 9.11 = 9.11, so 9.80 &gt; 9.11.
                </div>
                <div className="flex items-center gap-2">
                  <span className="ptg-dot size-1.5 rounded-full bg-foreground/60" />
                  <span className="ptg-dot size-1.5 rounded-full bg-foreground/60" />
                  <span className="ptg-dot size-1.5 rounded-full bg-foreground/60" />
                  <span className="text-[10px] font-medium uppercase tracking-[0.25em] text-muted-foreground">
                    ready for your question
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Features */}
      <section className="relative bg-background ptg-border-y">
        <div className="mx-auto w-full max-w-6xl px-4 py-16 md:py-24">
          <div className="mb-12 flex flex-col items-start gap-3 md:flex-row md:items-end md:justify-between">
            <h2 className="max-w-md text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
              Everything an orchestrator needs.
            </h2>
            <p className="max-w-sm text-sm text-muted-foreground">
              Five pillars, zero clutter. Reasoning, vision, live web access and
              total ownership of your data.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.35, delay: i * 0.05 }}
                className="group rounded-2xl bg-card/50 p-6 ptg-border transition-colors hover:border-primary/30 hover:bg-card/80"
              >
                <div
                  className={`mb-5 flex size-11 items-center justify-center rounded-xl ${f.tint}`}
                >
                  <f.icon className="size-5" />
                </div>
                <h3 className="text-base font-semibold tracking-tight">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {f.body}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Code strip */}
      <section className="ptg-stars">
        <div className="mx-auto grid w-full max-w-6xl gap-10 px-4 py-16 md:grid-cols-2 md:py-24">
          <div className="flex flex-col justify-center gap-4">
            <h2 className="text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
              One endpoint under the hood
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground md:text-base">
              A secure Convex action bridges your app and NVIDIA NIM. Keys live
              in the environment — the browser never sees them.
            </p>
            <ul className="mt-2 flex flex-col gap-2.5 text-sm text-muted-foreground">
              {[
                "POST /v1/chat/completions — OpenAI-compatible",
                "temperature 1 · top_p 0.95 · max_tokens 16384",
                "Text + image (vision) messages supported",
                "Tool-calling web RAG with inline citations",
              ].map((item) => (
                <li key={item} className="flex items-start gap-2.5">
                  <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-primary" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl bg-card/60 ptg-border shadow-2xl shadow-black/40 backdrop-blur">
            <div className="flex items-center gap-1.5 rounded-t-2xl px-4 py-3 ptg-border-b">
              <span className="size-2 rounded-full bg-rose-400/70" />
              <span className="size-2 rounded-full bg-amber-400/70" />
              <span className="size-2 rounded-full bg-emerald-400/70" />
              <span className="ml-3 text-[11px] font-medium tracking-wide text-muted-foreground">
                convex/nvidia.ts
              </span>
            </div>
            <pre className="overflow-x-auto p-5 text-xs leading-relaxed text-foreground/80">
              <code>{`POST /v1/chat/completions
Authorization: Bearer $MODEL_API_KEY  # stays server-side

{
  "model": "z-ai/glm-5.3-flash",
  "messages": [
    {"role": "user",
     "content": [
       {"type": "text",
        "text": "Describe this image."},
       {"type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,..."}}
     ]}
  ],
  "temperature": 1,
  "top_p": 0.95,
  "max_tokens": 16384,
  "stream": true
}`}</code>
            </pre>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="relative overflow-hidden ptg-border-t">
        <div className="ptg-stars absolute inset-0 opacity-60" />
        <div className="relative mx-auto flex w-full max-w-6xl flex-col items-center gap-6 px-4 py-16 text-center md:py-20">
          <Polyhedron size={56} glow={false} />
          <h2 className="max-w-2xl text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
            Your ideas. Multiplied.
          </h2>
          <p className="max-w-lg text-sm text-muted-foreground md:text-base">
            Sign in with email or jump in as a guest. Your first conversation is
            one click away.
          </p>
          <Link to="/auth">
            <Button
              size="lg"
              className="rounded-full bg-primary font-medium hover:bg-primary/90"
            >
              Get started free
              <ArrowRight className="size-4" />
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="ptg-border-t bg-background">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-4 px-4 py-8 text-xs text-muted-foreground md:flex-row">
          <div className="flex items-center gap-2.5">
            <Polyhedron size={22} glow={false} />
            <span className="font-semibold uppercase tracking-[0.3em] text-foreground">
              Pentagon
            </span>
          </div>
          <p className="tracking-wide">
            RESEARCH <span className="mx-1 text-border">/</span> BUILD{" "}
            <span className="mx-1 text-border">/</span> EXPLORE{" "}
            <span className="mx-1 text-border">/</span> EXECUTE
          </p>
          <p>
            Powered by NVIDIA NIM · {new Date().getFullYear()}
          </p>
        </div>
      </footer>
    </div>
  );
}
