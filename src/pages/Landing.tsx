import { motion } from "framer-motion";
import {
  ArrowRight,
  Bot,
  Cpu,
  Database,
  Globe,
  MessageSquare,
  Shield,
  Zap,
} from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";

const FEATURES = [
  {
    icon: MessageSquare,
    title: "Blazing chat",
    body: "A minimal workspace with history, rename, delete and copy — nothing you don't need.",
    bg: "bg-primary",
  },
  {
    icon: Cpu,
    title: "NVIDIA NIM engine",
    body: "z-ai/glm-5.3-flash with vision — send text and images via the OpenAI-compatible endpoint.",
    bg: "bg-secondary",
  },
  {
    icon: Database,
    title: "Persistent memory",
    body: "Every conversation is stored in Convex, so your history survives reloads.",
    bg: "bg-primary",
  },
  {
    icon: Shield,
    title: "Locked down",
    body: "Your API key stays server-side in a Convex action. Chats belong to you alone.",
    bg: "bg-secondary",
  },
  {
    icon: Globe,
    title: "Live web RAG",
    body: "Tavily search and Firecrawl scraping give the model current sources — cited under every answer.",
    bg: "bg-primary",
  },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-background">
      {/* Nav */}
      <header className="sticky top-0 z-40 bg-background nb-border-b">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2">
            <div className="flex size-9 items-center justify-center bg-primary nb-border nb-shadow-sm">
              <Zap className="size-5" />
            </div>
            <span className="text-lg font-black uppercase tracking-tight">
              NeoChat
            </span>
          </Link>
          <nav className="flex items-center gap-2">
            <Link to="/auth">
              <Button variant="ghost" className="font-bold uppercase">
                Sign in
              </Button>
            </Link>
            <Link to="/dashboard">
              <Button className="font-bold uppercase nb-press">
                Launch app
                <ArrowRight className="size-4" />
              </Button>
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="nb-grid-bg">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-8 px-4 py-20 text-center md:py-28">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="flex items-center gap-2 bg-card px-3 py-1 text-xs font-bold uppercase tracking-widest nb-border nb-shadow-sm"
          >
            <Bot className="size-3.5" />
            Powered by NVIDIA NIM
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.05 }}
            className="max-w-3xl text-4xl font-black uppercase leading-[1.05] tracking-tight md:text-6xl"
          >
            Loud answers,{" "}
            <span className="bg-primary px-2 nb-border nb-shadow">
              quiet interface
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.1 }}
            className="max-w-xl text-base font-medium text-muted-foreground md:text-lg"
          >
            NeoChat is a chatbot running{" "}
            <span className="bg-secondary px-1 font-bold text-foreground">
              z-ai/glm-5.3-flash
            </span>{" "}
            on NVIDIA NIM — OpenAI-compatible calls with text and image input,
            stored in your own Convex history, with live web search when it
            matters.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.15 }}
            className="flex flex-col items-center gap-3 sm:flex-row"
          >
            <Link to="/auth">
              <Button size="lg" className="font-black uppercase nb-press">
                Start chatting
                <ArrowRight className="size-4" />
              </Button>
            </Link>
            <Link to="/dashboard">
              <Button
                size="lg"
                variant="outline"
                className="font-black uppercase nb-press"
              >
                Try the demo
              </Button>
            </Link>
          </motion.div>

          {/* Hero block */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="mt-8 w-full max-w-3xl"
          >
            <div className="bg-card nb-border nb-offset">
              <div className="flex items-center justify-between gap-2 px-4 py-2 nb-border-b bg-primary">
                <p className="text-xs font-black uppercase tracking-widest">
                  neochat — live
                </p>
                <p className="text-xs font-bold uppercase">glm-5.3-flash</p>
              </div>
              <div className="flex flex-col gap-4 p-4 text-left md:p-6">
                <div className="self-end bg-secondary px-4 py-3 text-sm font-medium nb-border nb-shadow max-w-[80%]">
                  Which number is larger, 9.11 or 9.8?
                </div>
                <div className="bg-background px-4 py-3 text-sm leading-relaxed nb-border nb-shadow max-w-[80%]">
                  9.8 is larger. Compare the first decimal digit: 9.8 = 9.80
                  and 9.11 = 9.11, so 9.80 &gt; 9.11.
                </div>
                <div className="flex items-center gap-2">
                  <span className="nb-dot size-2 bg-foreground" />
                  <span className="nb-dot size-2 bg-foreground" />
                  <span className="nb-dot size-2 bg-foreground" />
                  <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                    ready for your question
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Features */}
      <section className="bg-card nb-border-y">
        <div className="mx-auto w-full max-w-6xl px-4 py-16 md:py-24">
          <div className="mb-10 flex flex-col items-start gap-3 md:flex-row md:items-end md:justify-between">
            <h2 className="max-w-md text-3xl font-black uppercase leading-tight tracking-tight md:text-4xl">
              Flat design. Sharp answers.
            </h2>
            <p className="max-w-sm text-sm font-medium text-muted-foreground">
              Five blocks, zero fluff. Everything is squared away — borders,
              buttons, and reasoning.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.35, delay: i * 0.05 }}
                className={`${f.bg} p-6 nb-border nb-press`}
              >
                <div className="mb-4 flex size-10 items-center justify-center bg-card nb-border">
                  <f.icon className="size-5" />
                </div>
                <h3 className="text-lg font-black uppercase tracking-tight">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm font-medium leading-relaxed text-foreground/80">
                  {f.body}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Code strip */}
      <section className="nb-grid-bg">
        <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-16 md:grid-cols-2 md:py-24">
          <div className="flex flex-col justify-center gap-4">
            <h2 className="text-3xl font-black uppercase leading-tight tracking-tight md:text-4xl">
              One endpoint under the hood
            </h2>
            <p className="text-sm font-medium leading-relaxed text-muted-foreground md:text-base">
              Your Python snippet, rebuilt as a secure Convex action. The key
              lives in the environment — the browser never sees it.
            </p>
            <ul className="flex flex-col gap-2 text-sm font-semibold">
              {[
                "POST /v1/chat/completions — OpenAI-compatible",
                "temperature 1 · top_p 0.95 · max_tokens 16384",
                "Text + image (vision) messages supported",
              ].map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <span className="mt-0.5 size-3 shrink-0 bg-primary nb-border" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="bg-foreground p-1 text-background nb-border nb-offset">
            <pre className="overflow-x-auto p-4 text-xs leading-relaxed md:text-sm">
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
      <section className="bg-primary nb-border-t">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-6 px-4 py-16 text-center md:py-20">
          <h2 className="max-w-2xl text-3xl font-black uppercase leading-tight tracking-tight md:text-5xl">
            Stop scrolling. Start asking.
          </h2>
          <p className="max-w-lg text-sm font-semibold md:text-base">
            Sign in with email or jump in as a guest. Your first chat is one
            click away.
          </p>
          <Link to="/auth">
            <Button
              size="lg"
              variant="outline"
              className="bg-card font-black uppercase nb-press"
            >
              Get started free
              <ArrowRight className="size-4" />
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-foreground text-background">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-4 px-4 py-8 text-sm font-bold uppercase tracking-widest md:flex-row">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center bg-primary text-foreground nb-border">
              <Zap className="size-4" />
            </div>
            NeoChat
          </div>
          <p className="text-xs">Built on NVIDIA NIM · Convex · {new Date().getFullYear()}</p>
        </div>
      </footer>
    </div>
  );
}
