import { Children, isValidElement, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  Copy,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  File,
  FileCode,
  FileSpreadsheet,
  FileText,
  Globe,
  Image as ImageIcon,
  Info,
  Layers,
  Loader2,
  Maximize2,
  Monitor,
  Presentation,
  RotateCw,
  Search,
  Server,
  Smartphone,
  Sparkles,
  Video,
  X,
} from 'lucide-react'

import { downloadGeneratedFile, fetchFilePreview, getFileBlobUrl, startLocalhostServer, type FilePreviewData } from '../api'
import { buildClientPdfBlobUrl } from '../lib/pdfGenerator'
import type { ChatMessage, ExecutionTrace, GeneratedFileInfo, SourcesUsed, TraceEntry } from '../types'

function base64ToBlob(base64: string, mimeType: string): Blob {
  const byteChars = atob(base64)
  const byteNumbers = new Uint8Array(byteChars.length)
  for (let i = 0; i < byteChars.length; i++) {
    byteNumbers[i] = byteChars.charCodeAt(i)
  }
  return new Blob([byteNumbers], { type: mimeType })
}

function triggerBlobDownload(blobUrl: string, filename: string) {
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function sanitizeMarkdownContent(raw: string): string {
  if (!raw) return ''
  let cleaned = raw.replace(/(?:#\s*)?```deliverable:[^\n]*\r?\n([\s\S]*?)(?:```|$)/gi, '$1')
  cleaned = cleaned.replace(/(?:#\s*)?```deliverable:[^\n]*(?:\r?\n|$)/gi, '')
  cleaned = cleaned.replace(/^[ \t]*DELIVERABLE:[^\r\n]+(?:\r?\n|$)/gim, '')
  return cleaned
}



function textFromNode(node: ReactNode): string {
  return Children.toArray(node).map((child) => {
    if (typeof child === 'string' || typeof child === 'number') return String(child)
    if (isValidElement<{ children?: ReactNode }>(child)) return textFromNode(child.props.children)
    return ''
  }).join('')
}

function CodePanel({ code, language, children }: { code: string; language: string; children: ReactNode }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }
  return <div className="group relative my-4 overflow-hidden rounded-xl border border-white/[0.09] bg-[#000000]">
    <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-2 text-micro uppercase tracking-[.16em] text-zinc-500">
      <span>{language || 'Code'}</span>
      <button onClick={() => void copy()} className="flex items-center gap-1.5 rounded-md px-2 py-1 normal-case tracking-normal text-zinc-400 transition hover:bg-white/[0.07] hover:text-white" aria-label="Copy code">
        {copied ? <Check size={12} /> : <Copy size={12} />}{copied ? 'Copied' : 'Copy'}
      </button>
    </div>
    <pre className="overflow-x-auto px-4 py-3 text-body leading-6 text-[#d4d8df]"><code>{children}</code></pre>
  </div>
}

function removeCalloutPrefix(node: ReactNode): ReactNode {
  return Children.map(node, (child) => {
    if (typeof child === 'string') {
      return child.replace(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/i, '')
    }
    if (isValidElement<{ children?: ReactNode }>(child)) {
      return {
        ...child,
        props: {
          ...child.props,
          children: removeCalloutPrefix(child.props.children),
        },
      }
    }
    return child
  })
}

function CustomBlockquote({ children }: { children: ReactNode }) {
  const text = textFromNode(children).trim()
  const match = text.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]/i)

  if (match) {
    const kind = match[1].toLowerCase() as 'note' | 'tip' | 'important' | 'warning' | 'caution'
    const cleanChildren = removeCalloutPrefix(children)

    const config = {
      note: {
        border: 'border-sky-500/40',
        bg: 'bg-sky-500/[0.08]',
        titleColor: 'text-sky-300',
        title: 'Note',
        icon: Info,
      },
      tip: {
        border: 'border-emerald-500/40',
        bg: 'bg-emerald-500/[0.08]',
        titleColor: 'text-emerald-300',
        title: 'Tip',
        icon: Sparkles,
      },
      important: {
        border: 'border-purple-500/40',
        bg: 'bg-purple-500/[0.08]',
        titleColor: 'text-purple-300',
        title: 'Important',
        icon: AlertCircle,
      },
      warning: {
        border: 'border-amber-500/40',
        bg: 'bg-amber-500/[0.08]',
        titleColor: 'text-amber-300',
        title: 'Warning',
        icon: AlertTriangle,
      },
      caution: {
        border: 'border-rose-500/40',
        bg: 'bg-rose-500/[0.08]',
        titleColor: 'text-rose-300',
        title: 'Caution',
        icon: AlertCircle,
      },
    }[kind] || {
      border: 'border-emerald-500/40',
      bg: 'bg-emerald-500/[0.08]',
      titleColor: 'text-emerald-300',
      title: 'Note',
      icon: Info,
    }

    const Icon = config.icon

    return (
      <div className={`my-4 overflow-hidden rounded-xl border ${config.border} ${config.bg} p-3.5 sm:p-4 text-small shadow-sm`}>
        <div className={`flex items-center gap-1.5 font-semibold uppercase tracking-wider text-[11px] ${config.titleColor} mb-2`}>
          <Icon size={14} className="shrink-0" />
          <span>{config.title}</span>
        </div>
        <div className="text-zinc-300 leading-relaxed [&>p:last-child]:mb-0 [&>p]:mb-2.5">
          {cleanChildren}
        </div>
      </div>
    )
  }

  return (
    <blockquote className="my-3.5 rounded-r-xl border-l-2 border-emerald-400/70 bg-white/[0.02] py-2.5 pl-4 pr-3 text-zinc-300 italic leading-relaxed">
      {children}
    </blockquote>
  )
}

const markdownComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-6 first:mt-0 flex items-center gap-2 border-b border-white/[0.08] pb-2 text-xl font-bold tracking-tight text-white">
      <span className="h-5 w-1 rounded-full bg-emerald-400 shrink-0" />
      <span>{children}</span>
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2.5 mt-5 first:mt-0 flex items-center gap-2 text-base sm:text-lg font-semibold tracking-tight text-zinc-100">
      <span className="h-4 w-1 rounded-full bg-emerald-400/80 shrink-0" />
      <span>{children}</span>
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 first:mt-0 flex items-center gap-1.5 text-sm sm:text-base font-semibold text-zinc-200">
      <span className="size-1.5 rounded-full bg-emerald-400/60 shrink-0" />
      <span>{children}</span>
    </h3>
  ),
  p: ({ children }) => <p className="mb-2.5 leading-[1.68] text-[#d4d7dc] last:mb-0 first:mt-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 ml-1 space-y-1.5 pl-3 border-l border-emerald-500/20">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 ml-5 list-decimal space-y-1.5 marker:font-semibold marker:text-emerald-400 text-zinc-300 leading-relaxed">{children}</ol>,
  li: ({ children }) => (
    <li className="relative pl-3 text-zinc-300 leading-relaxed before:absolute before:left-0 before:top-2.5 before:size-1.5 before:rounded-full before:bg-emerald-400/70">
      {children}
    </li>
  ),
  blockquote: ({ children }) => <CustomBlockquote>{children}</CustomBlockquote>,
  a: ({ href, children }) => {
    const url = safeExternalUrl(href)
    return url ? (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-emerald-300 underline decoration-emerald-300/30 underline-offset-4 hover:text-emerald-200 hover:decoration-emerald-300 transition-colors"
      >
        {children}
        <ExternalLink className="ml-1 inline" size={11} />
      </a>
    ) : (
      <span>{children}</span>
    )
  },
  code: ({ className, children }) => (
    <code
      className={
        className
          ? 'font-mono text-[.92em] text-emerald-200'
          : 'rounded-md border border-white/[0.08] bg-white/[0.06] px-1.5 py-0.5 font-mono text-[.88em] text-emerald-200'
      }
    >
      {children}
    </code>
  ),
  pre: ({ children }) => {
    const first = Children.toArray(children).find(isValidElement)
    const props = first && isValidElement<{ className?: string; children?: ReactNode }>(first) ? first.props : undefined
    const language = props?.className?.replace(/^language-/, '') || ''
    const source = textFromNode(children).replace(/\n$/, '')
    return <CodePanel code={source} language={language}>{children}</CodePanel>
  },
  table: ({ children }) => (
    <div className="my-3.5 overflow-x-auto rounded-xl border border-white/[0.1] bg-[#0c0d10] shadow-sm">
      <table className="w-full border-collapse text-left text-small">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-white/[0.1] bg-white/[0.04] text-[11px] font-semibold uppercase tracking-wider text-zinc-300">
      {children}
    </thead>
  ),
  tbody: ({ children }) => <tbody className="divide-y divide-white/[0.04]">{children}</tbody>,
  tr: ({ children }) => (
    <tr className="odd:bg-transparent even:bg-white/[0.015] hover:bg-white/[0.03] transition-colors">
      {children}
    </tr>
  ),
  th: ({ children }) => <th className="px-3.5 py-2 font-semibold text-zinc-200 whitespace-nowrap">{children}</th>,
  td: ({ children }) => <td className="px-3.5 py-2 text-zinc-300 text-small leading-normal">{children}</td>,
  hr: () => <hr className="my-5 border-white/[0.08]" />,
  img: ({ src, alt }) => <MarkdownImage src={src} alt={alt} />,
}

function MarkdownImage({ src, alt }: { src?: string; alt?: string }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) return null
  return (
    <figure className="my-3.5 overflow-hidden rounded-xl border border-white/[0.1] bg-black/40 shadow-xl">
      <img
        src={src}
        alt={alt || 'Illustration'}
        className="max-h-[500px] w-full object-contain mx-auto"
        loading="lazy"
        onError={() => setFailed(true)}
      />
      {alt && (
        <figcaption className="border-t border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-center text-caption text-zinc-400 italic">
          Figure: {alt}
        </figcaption>
      )}
    </figure>
  )
}



function safeExternalUrl(value: string | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null
  } catch { return null }
}

export function MarkdownAnswer({ content }: { content: string }) {
  const sanitized = useMemo(() => sanitizeMarkdownContent(content), [content])
  return (
    <div className="markdown-content min-w-0 break-words text-title leading-[1.68] text-[#d8d9dc]">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={markdownComponents}>
        {sanitized}
      </ReactMarkdown>
    </div>
  )
}

const TRACE_TITLES: Record<string, string> = {
  intent_router: 'Request routing',
  skill_router: 'Skill matching',
  web_search: 'Web search',
  retrieve_documents: 'Retrieved documents',
  vision_analysis: 'Vision analysis',
  context_assembler: 'Context assembly',
  generate_response: 'Model response',
  run_command: 'Tools run',
  conversation_context: 'Conversation context',
  transcription: 'Voice transcription',
  synthesis: 'Audio response',
}

function formatDuration(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`
}

function traceSummary(name: string, row: TraceEntry): string {
  const count = (key: string) => typeof row[key] === 'number' ? row[key] as number : null
  const status = typeof row.status === 'string' ? row.status : 'ran'
  if (status === 'skipped') return `Skipped · ${String(row.reason || 'not needed')}`
  if (status === 'failed') return `Could not complete${row.error ? ` · ${String(row.error)}` : ''}`
  if (name === 'retrieve_documents') {
    const n = count('result_count')
    return n === null ? 'Document retrieval completed' : `${n} ${n === 1 ? 'passage' : 'passages'} retrieved`
  }
  if (name === 'web_search') {
    const n = count('result_count')
    return n === null ? 'Web search completed' : `${n} ${n === 1 ? 'result' : 'results'} returned`
  }
  if (name === 'vision_analysis') {
    if (count('frames_sent') !== null) return `${count('frames_sent')} video frames · ${String(row.model_used || 'vision model')}`
    return `Image analyzed · ${String(row.model_used || 'vision model')}`
  }
  if (name === 'context_assembler') {
    const docs = count('document_count')
    const web = count('web_result_count')
    const parts = [docs !== null && `${docs} document passages`, web !== null && `${web} web results`].filter(Boolean)
    return parts.length ? parts.join(' · ') : 'Context prepared for the response'
  }
  if (name === 'conversation_context') return `${count('summary_word_count') ?? 0}-word summary · ${count('raw_message_count') ?? 0} recent messages`
  if (name === 'transcription') return `${String(row.provider || 'Speech provider')} · transcript added to this turn`
  if (name === 'synthesis') return `${String(row.provider || 'Speech provider')} · ${count('audio_bytes') ?? 0} audio bytes`
  if (name === 'generate_response') {
    const first = formatDuration(row.time_to_first_token_ms)
    return first ? `First token in ${first}` : 'Generated by the selected model'
  }
  return status === 'completed' ? 'Completed' : 'Completed successfully'
}

function TracePanel({ trace }: { trace: ExecutionTrace }) {
  const [expanded, setExpanded] = useState(false)
  const panelId = useId()
  const rows = Object.entries(trace).filter((entry): entry is [string, TraceEntry] => Boolean(entry[1]) && typeof entry[1] === 'object')
  if (!rows.length) return null
  const ran = rows.filter(([, row]) => row.status !== 'skipped').length
  return <section className={`trace-panel panel-enter mb-3 overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.018] ${expanded ? 'trace-panel-open' : ''}`}>
    <button type="button" aria-expanded={expanded} aria-controls={panelId} onClick={() => setExpanded((open) => !open)} className="flex w-full cursor-pointer list-none items-center gap-2.5 border-0 bg-transparent px-3.5 py-3 text-left text-small text-zinc-400 transition-colors duration-200 hover:text-zinc-200">
      <span className="grid size-5 place-items-center rounded-full border border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-300"><CheckCircle2 size={12} /></span>
      <span className="font-medium text-zinc-300">Reasoning steps</span>
      <span className="rounded-full bg-white/[0.06] px-1.5 py-0.5 text-caption text-zinc-500">{ran} of {rows.length} active</span>
      <ChevronDown size={13} className={`ml-auto transition-transform duration-200 ease-out ${expanded ? 'rotate-180' : ''}`} />
    </button>
    <div id={panelId} aria-hidden={!expanded} className={`trace-panel-body ${expanded ? 'trace-panel-body-open' : ''}`}>
      <div className="min-h-0 overflow-hidden">
        <div className="space-y-0 border-t border-white/[0.06] px-3.5 py-1">
          {rows.map(([name, row]) => {
            const status = String(row.status || 'ran')
            const skipped = status === 'skipped'
            const failed = status === 'failed'
            const duration = formatDuration(row.duration_ms)
            const Icon = failed ? AlertCircle : skipped ? CircleDashed : CheckCircle2
            return <div key={name} className="flex gap-3 border-b border-white/[0.045] py-2.5 last:border-0">
              <Icon size={14} className={`mt-0.5 shrink-0 ${failed ? 'text-rose-400' : skipped ? 'text-zinc-600' : 'text-emerald-400'}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className={`text-small font-medium ${skipped ? 'text-zinc-500' : 'text-zinc-300'}`}>{TRACE_TITLES[name] || name.replaceAll('_', ' ')}</span>
                  {duration && <span className="shrink-0 font-mono text-caption text-zinc-600">{duration}</span>}
                </div>
                <p className="mt-0.5 truncate text-micro text-zinc-500">{traceSummary(name, row)}</p>
              </div>
            </div>
          })}
        </div>
      </div>
    </div>
  </section>
}

type SourceItem = { key: string; title: string; url: string | null; subtitle: string }
type MediaItem = SourceItem & { kind: 'image' | 'video' }

/** Every source, grouped and counted, ready for the floating panel. */
function collectSources(sources: SourcesUsed) {
  const web: SourceItem[] = (sources.web || []).flatMap((source) => {
    const url = safeExternalUrl(source.url)
    return url ? [{ key: url, title: source.title || safeHost(url), url, subtitle: safeHost(url) }] : []
  })
  const documents: SourceItem[] = (sources.documents || []).map((source) => ({
    key: source.document_id,
    title: source.filename,
    url: null,
    subtitle: `${source.chunk_ids.length} passage${source.chunk_ids.length === 1 ? '' : 's'} referenced`,
  }))
  const media: MediaItem[] = []
  if (sources.image) {
    media.push({
      key: 'image',
      kind: 'image',
      title: `Image · ${sources.image.model_used}`,
      url: null,
      subtitle: sources.image.description_summary,
    })
  }
  if (sources.video) {
    media.push({
      key: 'video',
      kind: 'video',
      title: `Video · ${sources.video.frames_sent} frames`,
      url: null,
      subtitle: sources.video.description_summary,
    })
  }
  return { web, documents, media }
}

function safeHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/**
 * Sources collapse to a single trigger. Everything is behind one click in a
 * floating panel, so a long citation list never competes with the answer for
 * attention or pushes the conversation around as it arrives.
 */
function SourcesButton({ sources }: { sources: SourcesUsed }) {
  const { web, documents, media } = useMemo(() => collectSources(sources), [sources])
  const total = web.length + documents.length + media.length
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  if (!total) return null

  return <div ref={wrapRef} className="relative mt-3 w-full">
    <button
      type="button"
      onClick={() => setOpen((value) => !value)}
      aria-expanded={open}
      aria-haspopup="dialog"
      className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.09] bg-white/[0.025] px-2.5 py-1.5 text-micro text-zinc-300 transition-colors duration-200 hover:border-white/20 hover:bg-white/[0.06] hover:text-zinc-100"
    >
      <Layers size={11} className="shrink-0 text-zinc-500" />
      Sources
      <span className="rounded-full bg-white/[0.08] px-1.5 text-[10px] tabular-nums text-zinc-400">{total}</span>
    </button>
    {open ? (
      <div
        role="dialog"
        aria-label="Sources"
        // Anchored to the right edge on a phone, where a left-anchored panel
        // would run past the viewport, and to the trigger from sm up.
        className="panel-enter absolute bottom-full right-0 z-30 mb-2 w-[min(calc(100vw-2rem),420px)] overflow-hidden rounded-xl border border-white/[0.1] bg-[#0b0b0b]/97 shadow-[0_18px_50px_rgba(0,0,0,.75)] backdrop-blur-xl sm:left-0 sm:right-auto sm:w-[min(92vw,420px)]"
      >
        <div className="flex items-center justify-between border-b border-white/[0.07] px-3.5 py-2.5">
          <span className="text-caption font-medium uppercase tracking-[.16em] text-zinc-500">Sources</span>
          <button type="button" onClick={() => setOpen(false)} aria-label="Close sources" className="grid size-6 place-items-center rounded-md text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200">
            <X size={12} />
          </button>
        </div>
        <div className="max-h-[min(60vh,380px)] overflow-y-auto overscroll-contain p-1.5">
          {web.length > 0 && (
            <section>
              <h3 className="px-2.5 pb-1 pt-2 text-micro uppercase tracking-[.16em] text-zinc-600">Web</h3>
              <ul className="space-y-0.5">
                {web.map((item) => (
                  <li key={item.key}>
                    <a
                      href={item.url ?? '#'}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-start gap-2.5 rounded-lg px-2.5 py-2 transition-colors duration-150 hover:bg-white/[0.05]"
                    >
                      <ExternalLink size={12} className="mt-0.5 shrink-0 text-zinc-500" />
                      <span className="min-w-0">
                        <span className="block truncate text-small text-zinc-200">{item.title}</span>
                        <span className="block truncate text-micro text-zinc-500">{item.subtitle}</span>
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {documents.length > 0 && (
            <section>
              <h3 className="px-2.5 pb-1 pt-2 text-micro uppercase tracking-[.16em] text-zinc-600">Documents</h3>
              <ul className="space-y-0.5">
                {documents.map((item) => (
                  <li key={item.key} className="flex items-start gap-2.5 rounded-lg px-2.5 py-2">
                    <FileText size={12} className="mt-0.5 shrink-0 text-sky-300/80" />
                    <span className="min-w-0">
                      <span className="block truncate text-small text-zinc-200">{item.title}</span>
                      <span className="block truncate text-micro text-zinc-500">{item.subtitle}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {media.length > 0 && (
            <section>
              <h3 className="px-2.5 pb-1 pt-2 text-micro uppercase tracking-[.16em] text-zinc-600">Media</h3>
              <ul className="space-y-0.5">
                {media.map((item) => (
                  <li key={item.key} className="flex items-start gap-2.5 rounded-lg px-2.5 py-2">
                    {item.kind === 'image'
                      ? <ImageIcon size={12} className="mt-0.5 shrink-0 text-violet-300/80" />
                      : <Video size={12} className="mt-0.5 shrink-0 text-violet-300/80" />}
                    <span className="min-w-0">
                      <span className="block truncate text-small text-zinc-200">{item.title}</span>
                      <span className="block text-micro leading-5 text-zinc-500">{item.subtitle}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    ) : null}
  </div>
}

function formatFileSize(bytes: number): string {
  if (!bytes || bytes < 1024) return `${bytes || 0} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const FORMAT_CONFIG: Record<
  string,
  { label: string; icon: typeof FileText; color: string; badge: string; bg: string }
> = {
  pdf: { label: 'PDF', icon: FileText, color: 'text-rose-400', badge: 'border-rose-500/30 text-rose-300', bg: 'bg-rose-500/10' },
  docx: { label: 'Word', icon: FileText, color: 'text-sky-400', badge: 'border-sky-500/30 text-sky-300', bg: 'bg-sky-500/10' },
  xlsx: { label: 'Excel', icon: FileSpreadsheet, color: 'text-emerald-400', badge: 'border-emerald-500/30 text-emerald-300', bg: 'bg-emerald-500/10' },
  csv: { label: 'CSV', icon: FileSpreadsheet, color: 'text-teal-400', badge: 'border-teal-500/30 text-teal-300', bg: 'bg-teal-500/10' },
  pptx: { label: 'PowerPoint', icon: Presentation, color: 'text-amber-400', badge: 'border-amber-500/30 text-amber-300', bg: 'bg-amber-500/10' },
  html: { label: 'Website', icon: Globe, color: 'text-orange-400', badge: 'border-orange-500/30 text-orange-300', bg: 'bg-orange-500/10' },
  md: { label: 'Markdown', icon: FileCode, color: 'text-purple-400', badge: 'border-purple-500/30 text-purple-300', bg: 'bg-purple-500/10' },
  txt: { label: 'Text', icon: FileText, color: 'text-zinc-400', badge: 'border-zinc-500/30 text-zinc-300', bg: 'bg-zinc-500/10' },
  png: { label: 'PNG Image', icon: ImageIcon, color: 'text-violet-400', badge: 'border-violet-500/30 text-violet-300', bg: 'bg-violet-500/10' },
  jpg: { label: 'JPEG Image', icon: ImageIcon, color: 'text-violet-400', badge: 'border-violet-500/30 text-violet-300', bg: 'bg-violet-500/10' },
  jpeg: { label: 'JPEG Image', icon: ImageIcon, color: 'text-violet-400', badge: 'border-violet-500/30 text-violet-300', bg: 'bg-violet-500/10' },
  webp: { label: 'WebP Image', icon: ImageIcon, color: 'text-violet-400', badge: 'border-violet-500/30 text-violet-300', bg: 'bg-violet-500/10' },
  svg: { label: 'SVG Vector', icon: ImageIcon, color: 'text-violet-400', badge: 'border-violet-500/30 text-violet-300', bg: 'bg-violet-500/10' },
}


function parseCsvToRows(csvText: string, maxRows = 200): string[][] {
  const lines = csvText.split(/\r?\n/).filter((line) => line.trim().length > 0)
  return lines.slice(0, maxRows).map((line) => {
    const cells: string[] = []
    let inQuotes = false
    let current = ''
    for (let i = 0; i < line.length; i++) {
      const char = line[i]
      if (char === '"') {
        inQuotes = !inQuotes
      } else if (char === ',' && !inQuotes) {
        cells.push(current.trim())
        current = ''
      } else {
        current += char
      }
    }
    cells.push(current.trim())
    return cells
  })
}

function SpreadsheetPreview({
  sheets,
  csvRows,
}: {
  sheets?: Array<{ name: string; rows: string[][] }>
  csvRows?: string[][]
}) {
  const [activeSheetIdx, setActiveSheetIdx] = useState(0)
  const [search, setSearch] = useState('')

  const currentSheet = sheets ? sheets[activeSheetIdx] : null
  const rawRows = currentSheet ? currentSheet.rows : csvRows || []

  const header = rawRows[0] || []
  const dataRows = rawRows.slice(1)

  const filteredRows = useMemo(() => {
    if (!search.trim()) return dataRows
    const q = search.toLowerCase()
    return dataRows.filter((row) => row.some((cell) => cell.toLowerCase().includes(q)))
  }, [dataRows, search])

  if (!rawRows.length) return <p className="p-3 text-caption text-zinc-500">Empty spreadsheet</p>

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 pb-1">
        {sheets && sheets.length > 1 && (
          <div className="flex flex-wrap items-center gap-1">
            {sheets.map((s, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => {
                  setActiveSheetIdx(idx)
                  setSearch('')
                }}
                className={`rounded-md px-2.5 py-1 text-micro font-medium transition ${
                  activeSheetIdx === idx
                    ? 'border border-emerald-500/40 bg-emerald-500/20 text-emerald-200'
                    : 'border border-white/10 bg-white/[0.04] text-zinc-400 hover:text-white'
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}
        <div className="relative ml-auto flex items-center">
          <Search size={11} className="absolute left-2 text-zinc-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter cells..."
            className="h-7 w-40 rounded-md border border-white/10 bg-black/50 pl-6 pr-2 text-micro text-zinc-200 placeholder-zinc-600 focus:border-emerald-500/40 focus:outline-none sm:w-52"
          />
        </div>
      </div>

      <div className="max-h-80 overflow-auto rounded-lg border border-white/[0.08] bg-black/60">
        <table className="w-full border-collapse text-left text-micro font-mono text-zinc-300">
          <thead className="sticky top-0 z-10 bg-[#141820]">
            <tr>
              <th className="w-10 border-b border-r border-white/10 bg-black/40 px-2 py-1.5 text-center text-[10px] text-zinc-600">
                #
              </th>
              {header.map((col, idx) => (
                <th key={idx} className="border-b border-white/10 px-3 py-1.5 font-semibold text-zinc-200 whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((r, rIdx) => (
              <tr key={rIdx} className="border-b border-white/[0.04] odd:bg-white/[0.015] hover:bg-emerald-500/[0.04]">
                <td className="border-r border-white/[0.06] bg-black/20 px-2 py-1 text-center text-[10px] text-zinc-600 select-none">
                  {rIdx + 1}
                </td>
                {r.map((c, cIdx) => (
                  <td key={cIdx} className="px-3 py-1 text-zinc-400 whitespace-nowrap">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-[11px] text-zinc-500">
        <span>
          Showing {filteredRows.length} of {dataRows.length} rows · {header.length} columns
        </span>
      </div>
    </div>
  )
}

function PresentationPreview({
  slides,
}: {
  slides: Array<{ slide_number: number; title: string; items: string[]; tables?: string[][][] }>
}) {
  const [activeSlide, setActiveSlide] = useState(0)
  if (!slides || !slides.length) return <p className="p-3 text-caption text-zinc-500">No slides found</p>

  const slide = slides[activeSlide]

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b border-white/[0.08] pb-2">
        <span className="text-micro font-semibold uppercase tracking-wider text-amber-300/90">
          Slide {activeSlide + 1} of {slides.length}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={activeSlide === 0}
            onClick={() => setActiveSlide((i) => Math.max(0, i - 1))}
            className="flex size-7 items-center justify-center rounded border border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/10 disabled:opacity-30"
          >
            <ChevronLeft size={13} />
          </button>
          <button
            type="button"
            disabled={activeSlide === slides.length - 1}
            onClick={() => setActiveSlide((i) => Math.min(slides.length - 1, i + 1))}
            className="flex size-7 items-center justify-center rounded border border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/10 disabled:opacity-30"
          >
            <ChevronRight size={13} />
          </button>
        </div>
      </div>

      <div className="aspect-[16/9] w-full overflow-hidden rounded-xl border border-amber-500/20 bg-gradient-to-br from-[#0f172a] via-[#111827] to-[#0a0a0f] p-6 sm:p-8 flex flex-col justify-between shadow-2xl">
        <div>
          <h2 className="mb-4 text-lg font-bold text-white sm:text-2xl tracking-tight">
            {slide.title}
          </h2>
          <ul className="space-y-2.5 pl-1">
            {slide.items.map((item, idx) => (
              <li key={idx} className="flex items-start gap-2.5 text-small sm:text-body text-zinc-200">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-amber-400" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
        {slide.tables && slide.tables.length > 0 && (
          <div className="my-2 max-h-40 overflow-auto rounded-lg border border-white/10 bg-black/40">
            <table className="w-full border-collapse text-left text-micro text-zinc-300">
              <tbody>
                {slide.tables[0].map((r, rIdx) => (
                  <tr key={rIdx} className="border-b border-white/[0.06] odd:bg-white/[0.02]">
                    {r.map((c, cIdx) => (
                      <td key={cIdx} className="px-2.5 py-1">
                        {c}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-white/[0.08] pt-2 text-[10px] text-zinc-500">
          <span>Pentagon Presentation</span>
          <span>Slide {slide.slide_number}</span>
        </div>
      </div>
    </div>
  )
}

function DocxPreview({
  elements,
}: {
  elements: Array<{ kind: string; text?: string; rows?: string[][] }>
}) {
  if (!elements || !elements.length) return <p className="p-3 text-caption text-zinc-500">Empty document</p>

  return (
    <div className="max-h-[500px] overflow-y-auto rounded-xl border border-white/[0.08] bg-[#141417] p-6 sm:p-8 text-zinc-200 shadow-inner space-y-3 font-sans">
      {elements.map((el, idx) => {
        if (el.kind === 'h1') {
          return <h1 key={idx} className="mt-4 mb-2 text-xl font-bold text-white border-b border-white/10 pb-1">{el.text}</h1>
        }
        if (el.kind === 'h2') {
          return <h2 key={idx} className="mt-3 mb-1.5 text-lg font-semibold text-zinc-100">{el.text}</h2>
        }
        if (el.kind === 'h3') {
          return <h3 key={idx} className="mt-2 mb-1 text-base font-medium text-zinc-200">{el.text}</h3>
        }
        if (el.kind === 'bullet') {
          return (
            <div key={idx} className="flex items-start gap-2 pl-2 text-small text-zinc-300">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-sky-400" />
              <span>{el.text}</span>
            </div>
          )
        }
        if (el.kind === 'table' && el.rows) {
          return (
            <div key={idx} className="my-3 overflow-x-auto rounded-lg border border-white/10">
              <table className="w-full border-collapse text-left text-small text-zinc-300">
                <thead>
                  <tr className="bg-white/[0.04]">
                    {el.rows[0]?.map((col, cIdx) => (
                      <th key={cIdx} className="border-b border-white/10 px-3 py-1.5 font-semibold text-zinc-200">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {el.rows.slice(1).map((r, rIdx) => (
                    <tr key={rIdx} className="border-b border-white/[0.04] odd:bg-white/[0.02]">
                      {r.map((c, cIdx) => (
                        <td key={cIdx} className="px-3 py-1.5 text-zinc-400">
                          {c}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        return <p key={idx} className="text-small leading-relaxed text-zinc-300">{el.text}</p>
      })}
    </div>
  )
}

function PdfPreview({
  file,
  blobUrl,
  pdfPages,
  pdfPageImages,
}: {
  file: GeneratedFileInfo
  blobUrl: string | null
  pdfPages?: string[]
  pdfPageImages?: string[]
}) {
  const hasPageImages = Boolean(pdfPageImages && pdfPageImages.length > 0)
  const [viewMode, setViewMode] = useState<'document' | 'pdf' | 'text'>(hasPageImages ? 'document' : 'pdf')
  const [activePage, setActivePage] = useState(0)
  const totalPages = (hasPageImages ? pdfPageImages?.length : pdfPages?.length) || 1

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 pb-1 border-b border-white/[0.06]">
        <div className="flex items-center gap-1.5">
          {hasPageImages && (
            <button
              type="button"
              onClick={() => setViewMode('document')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-micro font-medium transition ${
                viewMode === 'document'
                  ? 'border border-rose-500/40 bg-rose-500/20 text-rose-200 shadow-sm'
                  : 'border border-white/10 bg-white/[0.04] text-zinc-400 hover:text-white'
              }`}
            >
              <FileText size={12} />
              <span>Document View</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setViewMode('pdf')}
            className={`rounded-md px-2.5 py-1 text-micro font-medium transition ${
              viewMode === 'pdf'
                ? 'border border-rose-500/40 bg-rose-500/20 text-rose-200 shadow-sm'
                : 'border border-white/10 bg-white/[0.04] text-zinc-400 hover:text-white'
            }`}
          >
            Native PDF Viewer
          </button>
          {pdfPages && pdfPages.length > 0 && (
            <button
              type="button"
              onClick={() => setViewMode('text')}
              className={`rounded-md px-2.5 py-1 text-micro font-medium transition ${
                viewMode === 'text'
                  ? 'border border-rose-500/40 bg-rose-500/20 text-rose-200 shadow-sm'
                  : 'border border-white/10 bg-white/[0.04] text-zinc-400 hover:text-white'
              }`}
            >
              Extracted Text ({pdfPages.length})
            </button>
          )}
        </div>

        {totalPages > 1 && (
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={activePage === 0}
              onClick={() => setActivePage((i) => Math.max(0, i - 1))}
              className="flex size-7 items-center justify-center rounded border border-white/10 text-zinc-300 hover:bg-white/10 disabled:opacity-30"
              title="Previous page"
            >
              <ChevronLeft size={13} />
            </button>
            <span className="text-caption font-medium text-zinc-300 px-1">
              Page {activePage + 1} of {totalPages}
            </span>
            <button
              type="button"
              disabled={activePage === totalPages - 1}
              onClick={() => setActivePage((i) => Math.min(totalPages - 1, i + 1))}
              className="flex size-7 items-center justify-center rounded border border-white/10 text-zinc-300 hover:bg-white/10 disabled:opacity-30"
              title="Next page"
            >
              <ChevronRight size={13} />
            </button>
          </div>
        )}
      </div>

      {viewMode === 'document' && hasPageImages ? (
        <div className="flex flex-col items-center justify-center p-3 sm:p-5 bg-[#09090b] rounded-xl border border-white/[0.07] overflow-hidden">
          <div className="relative max-h-[620px] overflow-auto rounded-lg shadow-2xl border border-white/10 bg-white p-1">
            <img
              src={pdfPageImages![activePage]}
              alt={`Page ${activePage + 1}`}
              className="max-h-[600px] w-auto object-contain mx-auto rounded"
            />
          </div>
        </div>
      ) : viewMode === 'pdf' ? (
        blobUrl ? (
          <iframe
            src={blobUrl}
            className="h-[520px] w-full rounded-xl border border-white/10 bg-white shadow-xl"
            title={file.filename}
          />
        ) : (
          <div className="flex h-64 items-center justify-center gap-2 rounded-xl border border-white/10 bg-black/40 text-small text-zinc-400">
            <Loader2 size={16} className="animate-spin text-rose-400" />
            <span>Loading PDF reader...</span>
          </div>
        )
      ) : (
        <div className="max-h-[500px] overflow-y-auto rounded-xl border border-white/10 bg-black/60 p-5 font-mono text-small leading-relaxed text-zinc-300 whitespace-pre-wrap">
          {pdfPages?.[activePage] || 'No text extracted for this page.'}
        </div>
      )}
    </div>
  )
}

function MarkdownPreview({ text }: { text: string }) {
  const [mode, setMode] = useState<'rendered' | 'source'>('rendered')
  const [copied, setCopied] = useState(false)

  async function copySource() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between pb-1">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setMode('rendered')}
            className={`rounded-md px-2.5 py-1 text-micro font-medium transition ${
              mode === 'rendered'
                ? 'border border-purple-500/40 bg-purple-500/20 text-purple-200'
                : 'border border-white/10 bg-white/[0.04] text-zinc-400 hover:text-white'
            }`}
          >
            Formatted Document
          </button>
          <button
            type="button"
            onClick={() => setMode('source')}
            className={`rounded-md px-2.5 py-1 text-micro font-medium transition ${
              mode === 'source'
                ? 'border border-purple-500/40 bg-purple-500/20 text-purple-200'
                : 'border border-white/10 bg-white/[0.04] text-zinc-400 hover:text-white'
            }`}
          >
            Raw Markdown
          </button>
        </div>
        <button
          type="button"
          onClick={() => void copySource()}
          className="flex items-center gap-1 rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-micro text-zinc-300 hover:bg-white/10"
        >
          {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>

      {mode === 'rendered' ? (
        <div className="max-h-[500px] overflow-y-auto rounded-xl border border-white/[0.08] bg-black/50 p-5 shadow-inner">
          <MarkdownAnswer content={text} />
        </div>
      ) : (
        <pre className="max-h-[500px] overflow-x-auto rounded-xl border border-white/[0.08] bg-black/70 p-4 font-mono text-micro leading-5 text-zinc-300">
          <code>{text}</code>
        </pre>
      )}
    </div>
  )
}

function TextPreview({ text, format }: { text: string; format: string }) {
  const [copied, setCopied] = useState(false)

  async function copyText() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between pb-1">
        <span className="text-micro uppercase tracking-wider text-zinc-500">{format} Code / Text</span>
        <button
          type="button"
          onClick={() => void copyText()}
          className="flex items-center gap-1 rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-micro text-zinc-300 hover:bg-white/10"
        >
          {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <pre className="max-h-[500px] overflow-x-auto rounded-xl border border-white/[0.08] bg-black/70 p-4 font-mono text-micro leading-5 text-zinc-300">
        <code>{text}</code>
      </pre>
    </div>
  )
}

function HtmlWebsitePreview({
  html,
  filename,
  fileId,
}: {
  html: string
  filename: string
  fileId?: string
}) {
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview')
  const [viewport, setViewport] = useState<'desktop' | 'mobile'>('desktop')
  const [copied, setCopied] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [serverUrl, setServerUrl] = useState<string | null>(null)
  const [serverPort, setServerPort] = useState<number | null>(null)
  const [isHosting, setIsHosting] = useState(false)
  const [copiedLocalhost, setCopiedLocalhost] = useState(false)
  const [hostError, setHostError] = useState<string | null>(null)

  async function copyCode() {
    await navigator.clipboard.writeText(html)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  function handleOpenNewTab() {
    try {
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const win = window.open(url, '_blank', 'noopener,noreferrer')
      if (win) {
        setTimeout(() => URL.revokeObjectURL(url), 60000)
      }
    } catch {
      const win = window.open('', '_blank')
      if (win) {
        win.document.open()
        win.document.write(html)
        win.document.close()
      }
    }
  }

  async function handleRunLocalhost() {
    setIsHosting(true)
    setHostError(null)
    try {
      const res = await startLocalhostServer({
        file_id: fileId,
        html: html,
        title: filename,
      })
      if (res && res.url) {
        setServerUrl(res.url)
        setServerPort(res.port)
        window.open(res.url, '_blank', 'noopener,noreferrer')
      }
    } catch (err) {
      console.error('Failed to launch localhost server:', err)
      setHostError(err instanceof Error ? err.message : 'Could not launch localhost server')
    } finally {
      setIsHosting(false)
    }
  }

  async function copyLocalhostUrl() {
    if (!serverUrl) return
    await navigator.clipboard.writeText(serverUrl)
    setCopiedLocalhost(true)
    setTimeout(() => setCopiedLocalhost(false), 1500)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.08] pb-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-white/10 bg-black/40 p-0.5">
            <button
              type="button"
              onClick={() => setViewMode('preview')}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-micro font-medium transition ${
                viewMode === 'preview'
                  ? 'bg-orange-500/20 text-orange-200 border border-orange-500/30 shadow-sm'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <Globe size={12} className="text-orange-400" />
              <span>Interactive Preview</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode('code')}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-micro font-medium transition ${
                viewMode === 'code'
                  ? 'bg-orange-500/20 text-orange-200 border border-orange-500/30 shadow-sm'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <FileCode size={12} className="text-orange-400" />
              <span>Source Code</span>
            </button>
          </div>

          {viewMode === 'preview' && (
            <div className="hidden sm:flex items-center rounded-lg border border-white/10 bg-black/40 p-0.5">
              <button
                type="button"
                onClick={() => setViewport('desktop')}
                title="Desktop View (100%)"
                className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-micro font-medium transition ${
                  viewport === 'desktop'
                    ? 'bg-white/10 text-white'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                <Monitor size={12} />
                <span>Desktop</span>
              </button>
              <button
                type="button"
                onClick={() => setViewport('mobile')}
                title="Mobile View (390px)"
                className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-micro font-medium transition ${
                  viewport === 'mobile'
                    ? 'bg-white/10 text-white'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                <Smartphone size={12} />
                <span>Mobile</span>
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {viewMode === 'preview' && (
            <button
              type="button"
              onClick={() => setReloadKey((k) => k + 1)}
              title="Reload preview"
              className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1 text-micro text-zinc-300 hover:bg-white/10 transition"
            >
              <RotateCw size={11} />
              <span className="hidden sm:inline">Reload</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => void handleRunLocalhost()}
            disabled={isHosting}
            title={serverUrl ? `Live on ${serverUrl}` : 'Run website on live localhost HTTP server'}
            className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-micro font-medium transition ${
              serverUrl
                ? 'border-emerald-500/40 bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 shadow-sm'
                : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
            }`}
          >
            {isHosting ? (
              <Loader2 size={11} className="animate-spin text-emerald-400" />
            ) : (
              <Server size={11} className={serverUrl ? 'text-emerald-400' : 'text-emerald-300'} />
            )}
            <span>{serverUrl ? `Live :${serverPort}` : 'Run on Localhost'}</span>
          </button>

          <button
            type="button"
            onClick={handleOpenNewTab}
            title="Open website in full browser tab"
            className="flex items-center gap-1.5 rounded-md border border-orange-500/30 bg-orange-500/15 px-2.5 py-1 text-micro font-medium text-orange-300 hover:bg-orange-500/25 transition"
          >
            <ExternalLink size={11} />
            <span>Open in Tab</span>
          </button>

          {viewMode === 'code' && (
            <button
              type="button"
              onClick={() => void copyCode()}
              className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1 text-micro text-zinc-300 hover:bg-white/10 transition"
            >
              {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          )}
        </div>
      </div>

      {serverUrl && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-500/30 bg-emerald-950/40 px-3.5 py-2 text-micro text-emerald-200">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="font-semibold text-emerald-300">Localhost Server:</span>
            <a
              href={serverUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-emerald-200 underline decoration-emerald-500/50 underline-offset-2 hover:text-white"
            >
              {serverUrl}
            </a>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void copyLocalhostUrl()}
              className="flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/20 px-2.5 py-1 text-micro font-medium text-emerald-200 hover:bg-emerald-500/30 transition"
            >
              {copiedLocalhost ? <Check size={10} className="text-emerald-300" /> : <Copy size={10} />}
              <span>{copiedLocalhost ? 'Copied' : 'Copy URL'}</span>
            </button>
            <a
              href={serverUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/30 px-2.5 py-1 text-micro font-semibold text-white hover:bg-emerald-500/40 transition"
            >
              <ExternalLink size={10} />
              <span>Open Localhost</span>
            </a>
          </div>
        </div>
      )}

      {hostError && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-1.5 text-micro text-red-300">
          <AlertCircle size={12} className="shrink-0 text-red-400" />
          <span>{hostError}</span>
        </div>
      )}

      {viewMode === 'preview' ? (
        <div
          className={`w-full overflow-hidden rounded-xl border border-white/10 p-2 sm:p-4 transition-all ${
            viewport === 'mobile'
              ? 'bg-gradient-to-b from-zinc-900 to-black flex justify-center'
              : 'bg-zinc-950'
          }`}
        >
          {viewport === 'desktop' ? (
            <iframe
              key={reloadKey}
              srcDoc={html}
              title={filename}
              sandbox="allow-scripts allow-forms allow-modals allow-popups"
              className="h-[580px] w-full rounded-lg border border-black/20 bg-white shadow-2xl transition-all"
            />
          ) : (
            <div className="relative mx-auto flex flex-col items-center py-2">
              <div className="relative h-[620px] w-[390px] max-w-full overflow-hidden rounded-[38px] border-[8px] border-zinc-800 bg-black shadow-2xl ring-1 ring-white/10">
                <div className="absolute top-2 left-1/2 z-20 flex h-4 w-20 -translate-x-1/2 items-center justify-center rounded-full bg-zinc-900">
                  <div className="h-1 w-8 rounded-full bg-zinc-700" />
                </div>
                <iframe
                  key={reloadKey}
                  srcDoc={html}
                  title={filename}
                  sandbox="allow-scripts allow-forms allow-modals allow-popups"
                  className="h-full w-full bg-white pt-6"
                />
              </div>
              <span className="mt-2 font-mono text-[10px] text-zinc-500">Mobile Device Viewport (390px)</span>
            </div>
          )}
        </div>
      ) : (
        <pre className="max-h-[560px] overflow-x-auto rounded-xl border border-white/[0.08] bg-black/80 p-4 font-mono text-micro leading-relaxed text-zinc-200">
          <code>{html}</code>
        </pre>
      )}
    </div>
  )
}

function ImageFilePreview({
  imageUrl,
  filename,
}: {
  imageUrl?: string
  filename: string
}) {
  const [zoom, setZoom] = useState(false)
  if (!imageUrl) {
    return (
      <div className="flex h-56 items-center justify-center gap-2 rounded-xl border border-white/10 bg-black/40 text-small text-zinc-400">
        <Loader2 size={16} className="animate-spin text-violet-400" />
        <span>Loading image preview...</span>
      </div>
    )
  }

  return (
    <div className="relative group flex flex-col items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-black/50 p-2 sm:p-4">
      <img
        src={imageUrl}
        alt={filename}
        className={`max-h-[500px] w-auto max-w-full rounded-lg object-contain transition-transform duration-200 ${
          zoom ? 'scale-125 cursor-zoom-out' : 'cursor-zoom-in'
        }`}
        onClick={() => setZoom(!zoom)}
      />
      <div className="mt-2 text-micro text-zinc-500">
        Click image to {zoom ? 'reset zoom' : 'zoom in'}
      </div>
    </div>
  )
}

function GeneratedFileCard({ file, messageContent }: { file: GeneratedFileInfo; messageContent?: string }) {
  const [downloading, setDownloading] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewData, setPreviewData] = useState<FilePreviewData | null>(null)
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const fmt = (file.format || '').toLowerCase()
  const isImage = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(fmt)
  const conf = FORMAT_CONFIG[fmt] || {
    label: fmt.toUpperCase() || 'FILE',
    icon: File,
    color: 'text-zinc-400',
    badge: 'border-zinc-500/30 text-zinc-300',
    bg: 'bg-zinc-500/10',
  }
  const IconComponent = conf.icon

  useEffect(() => {
    return () => {
      if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl)
    }
  }, [pdfBlobUrl])

  useEffect(() => {
    let cancelled = false

    async function initDeliverable() {
      try {
        setPreviewLoading(true)
        setPreviewError(null)

        // Path A: Client-side self-contained data (Base64) - ZERO network dependency (Claude/ChatGPT style)
        if (file.data_base64) {
          const mime = file.media_type || (fmt === 'pdf' ? 'application/pdf' : 'application/octet-stream')
          const blob = base64ToBlob(file.data_base64, mime)
          const bUrl = URL.createObjectURL(blob)
          if (!cancelled) {
            if (fmt === 'pdf') setPdfBlobUrl(bUrl)
            const text = file.preview_text || messageContent || ''
            const pages = file.pdf_pages && file.pdf_pages.length > 0 
              ? file.pdf_pages 
              : (text ? text.split(/\n\s*---\s*\n/) : [])
            setPreviewData({
              id: file.id,
              filename: file.filename,
              format: file.format,
              media_type: file.media_type,
              size: file.size,
              preview: isImage ? 'image' : 'bytes',
              text,
              pdf_pages: pages,
              page_count: pages.length || 1,
              image_data_url: isImage ? `data:${mime};base64,${file.data_base64}` : undefined,
            })
            setPreviewLoading(false)
          }
          return
        }

        // Path B: Pure client-side PDF/doc compilation from preview text or message content
        const sourceText = file.preview_text || messageContent
        if (fmt === 'pdf' && sourceText && sourceText.trim().length > 20) {
          const docTitle = file.filename.replace(/\.pdf$/i, '').replace(/_/g, ' ')
          const built = await buildClientPdfBlobUrl(docTitle, sourceText)
          if (!cancelled) {
            setPdfBlobUrl(built.blobUrl)
            setPreviewData({
              id: file.id,
              filename: file.filename,
              format: 'pdf',
              media_type: 'application/pdf',
              size: built.bytes.length,
              preview: 'bytes',
              text: sourceText,
              pdf_pages: built.pagesText.length > 0 ? built.pagesText : [sourceText],
              page_count: built.pageCount,
            })
            setPreviewLoading(false)
          }
          return
        }

        // Path C: Fallback to server endpoint
        const [data, blob] = await Promise.all([
          fetchFilePreview(file.id).catch(() => null),
          fmt === 'pdf' ? getFileBlobUrl(file.id).catch(() => null) : Promise.resolve(null),
        ])

        if (!cancelled) {
          if (data) {
            setPreviewData(data)
            if (blob) setPdfBlobUrl(blob)
          } else if (sourceText) {
            // Serverless isolate didn't have file in memory: compile on client side!
            const docTitle = file.filename.replace(/\.pdf$/i, '').replace(/_/g, ' ')
            const built = await buildClientPdfBlobUrl(docTitle, sourceText)
            setPdfBlobUrl(built.blobUrl)
            setPreviewData({
              id: file.id,
              filename: file.filename,
              format: file.format,
              media_type: 'application/pdf',
              size: built.bytes.length,
              preview: 'bytes',
              text: sourceText,
              pdf_pages: built.pagesText,
              page_count: built.pageCount,
            })
          } else {
            setPreviewError('File preview currently unavailable')
          }
          setPreviewLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setPreviewError(err instanceof Error ? err.message : 'Could not load preview')
          setPreviewLoading(false)
        }
      }
    }

    initDeliverable()

    return () => {
      cancelled = true
    }
  }, [
    file.id,
    file.data_base64,
    file.preview_text,
    file.filename,
    file.format,
    file.media_type,
    file.size,
    file.pdf_pages,
    fmt,
    isImage,
    messageContent,
  ])

  async function handleDownload() {
    if (downloading) return
    try {
      setDownloading(true)
      // 1. Instant download from local PDF blob URL
      if (pdfBlobUrl) {
        triggerBlobDownload(pdfBlobUrl, file.filename)
        return
      }
      // 2. Instant download from base64
      if (file.data_base64) {
        const mime = file.media_type || (fmt === 'pdf' ? 'application/pdf' : 'application/octet-stream')
        const blob = base64ToBlob(file.data_base64, mime)
        const url = URL.createObjectURL(blob)
        triggerBlobDownload(url, file.filename)
        setTimeout(() => URL.revokeObjectURL(url), 2000)
        return
      }
      // 3. Instant client PDF or Spreadsheet build
      const sourceText = file.preview_text || messageContent
      if (fmt === 'pdf' && sourceText) {
        const docTitle = file.filename.replace(/\.pdf$/i, '').replace(/_/g, ' ')
        const built = await buildClientPdfBlobUrl(docTitle, sourceText)
        triggerBlobDownload(built.blobUrl, file.filename)
        return
      }
      if ((fmt === 'xlsx' || fmt === 'csv') && sourceText) {
        const blob = new Blob([sourceText], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        triggerBlobDownload(url, file.filename)
        setTimeout(() => URL.revokeObjectURL(url), 2000)
        return
      }
      // 4. Fallback to API download
      await downloadGeneratedFile(file.id, file.filename)
    } catch (err) {
      console.error('Download failed:', err)
    } finally {
      setDownloading(false)
    }
  }

  async function togglePreview() {
    if (previewOpen) {
      setPreviewOpen(false)
      return
    }
    setPreviewOpen(true)
  }

  async function openFullscreen() {
    setFullscreen(true)
  }

  function renderPreviewBody() {
    if (previewLoading) {
      return (
        <div className="flex items-center justify-center gap-2 py-8 text-small text-zinc-400">
          <Loader2 size={16} className="animate-spin text-emerald-400" />
          <span>Rendering {conf.label} preview...</span>
        </div>
      )
    }

    if (previewError) {
      return (
        <div className="flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-small text-rose-300">
          <AlertCircle size={15} className="shrink-0" />
          <span>{previewError}</span>
        </div>
      )
    }

    if (!previewData) return null

    return (
      <div className="space-y-3">
        {previewData.truncated && (
          <div className="text-caption text-amber-400/90">
            Preview is condensed for display. Download file for complete content.
          </div>
        )}

        {isImage && (
          <ImageFilePreview imageUrl={previewData.image_data_url} filename={file.filename} />
        )}

        {fmt === 'pdf' && (
          <PdfPreview file={file} blobUrl={pdfBlobUrl} pdfPages={previewData.pdf_pages} pdfPageImages={previewData.pdf_page_images} />
        )}

        {fmt === 'xlsx' && (
          <SpreadsheetPreview sheets={previewData.sheets} csvRows={parseCsvToRows(previewData.text || '')} />
        )}

        {fmt === 'csv' && (
          <SpreadsheetPreview csvRows={parseCsvToRows(previewData.text || '')} />
        )}

        {fmt === 'pptx' && (
          <PresentationPreview slides={previewData.slides || []} />
        )}

        {fmt === 'docx' && (
          <DocxPreview elements={previewData.docx_elements || []} />
        )}

        {fmt === 'md' && (
          <MarkdownPreview text={previewData.text || ''} />
        )}

        {fmt === 'html' && (
          <HtmlWebsitePreview html={previewData.text || ''} filename={file.filename} fileId={file.id} />
        )}

        {fmt === 'txt' && (
          <TextPreview text={previewData.text || ''} format={fmt} />
        )}
      </div>
    )
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#121214] transition-all hover:border-white/[0.15] shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 sm:p-3.5">
          <div className="flex min-w-0 items-center gap-3">
            <div className={`grid size-10 shrink-0 place-items-center rounded-xl border border-white/[0.08] ${conf.bg} ${conf.color} shadow-sm`}>
              <IconComponent size={20} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-body font-semibold text-zinc-100" title={file.filename}>
                  {file.filename}
                </span>
                <span className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${conf.badge} ${conf.bg}`}>
                  {conf.label}
                </span>
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-micro text-zinc-500">
                <span className="font-medium text-zinc-400">{formatFileSize(file.size)}</span>
                <span>·</span>
                <span className="truncate">{file.media_type}</span>
                <span>·</span>
                <span className="text-emerald-400/80">Ready to download</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={togglePreview}
              className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-micro font-medium transition ${
                previewOpen
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                  : 'border-white/[0.1] bg-white/[0.03] text-zinc-300 hover:border-white/20 hover:bg-white/[0.07] hover:text-white'
              }`}
              aria-label={previewOpen ? 'Hide preview' : 'Preview file'}
            >
              {previewOpen ? <EyeOff size={13} /> : <Eye size={13} />}
              <span>{previewOpen ? 'Hide' : 'Preview'}</span>
            </button>
            <button
              type="button"
              onClick={openFullscreen}
              className="flex size-8 items-center justify-center rounded-lg border border-white/[0.1] bg-white/[0.03] text-zinc-300 transition hover:border-white/20 hover:bg-white/[0.07] hover:text-white"
              title="Expand to Fullscreen"
              aria-label="Expand preview"
            >
              <Maximize2 size={13} />
            </button>
            <button
              type="button"
              onClick={() => void handleDownload()}
              disabled={downloading}
              className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-micro font-semibold text-emerald-300 transition hover:bg-emerald-500/25 hover:text-emerald-100 disabled:opacity-50 shadow-sm"
              aria-label="Download generated document"
            >
              {downloading ? <Loader2 size={13} className="animate-spin text-emerald-400" /> : <Download size={13} />}
              <span>{downloading ? 'Downloading...' : 'Download'}</span>
            </button>
          </div>
        </div>

        {previewOpen && (
          <div className="border-t border-white/[0.07] bg-[#0c0c0e] p-3 sm:p-4">
            {renderPreviewBody()}
          </div>
        )}
      </div>

      {fullscreen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-3 sm:p-6"
        >
          <div className="relative flex h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#111114] shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/[0.08] px-5 py-3.5 bg-[#141418]">
              <div className="flex items-center gap-3 min-w-0">
                <div className={`grid size-8 shrink-0 place-items-center rounded-lg border border-white/10 ${conf.bg} ${conf.color}`}>
                  <IconComponent size={16} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-base font-semibold text-white">{file.filename}</span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${conf.badge} ${conf.bg}`}>
                      {conf.label}
                    </span>
                  </div>
                  <span className="text-caption text-zinc-500">{formatFileSize(file.size)}</span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void handleDownload()}
                  disabled={downloading}
                  className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-small font-medium text-emerald-300 transition hover:bg-emerald-500/25 disabled:opacity-50"
                >
                  {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                  <span>Download</span>
                </button>
                <button
                  type="button"
                  onClick={() => setFullscreen(false)}
                  className="grid size-8 place-items-center rounded-lg border border-white/10 bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
                  aria-label="Close fullscreen preview"
                >
                  <X size={15} />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 sm:p-6 bg-[#0a0a0c] flex items-center justify-center">
              {isImage && previewData?.image_data_url ? (
                <div className="flex flex-col items-center justify-center max-w-full">
                  <img
                    src={previewData.image_data_url}
                    alt={file.filename}
                    className="max-h-[80vh] w-auto max-w-full rounded-xl object-contain shadow-2xl border border-white/10"
                  />
                  <span className="mt-3 text-caption text-zinc-400">{file.filename}</span>
                </div>
              ) : (
                <div className="w-full h-full">{renderPreviewBody()}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function GeneratedFilesList({ files, messageContent }: { files: GeneratedFileInfo[]; messageContent?: string }) {
  if (!files || files.length === 0) return null
  return (
    <div className="mt-4 space-y-2.5">
      <div className="flex items-center gap-2 text-micro font-semibold uppercase tracking-[.14em] text-zinc-400">
        <FileText size={13} className="text-emerald-400" />
        <span>Generated Deliverables ({files.length})</span>
      </div>
      <div className="grid gap-2.5">
        {files.map((file) => (
          <GeneratedFileCard key={file.id} file={file} messageContent={messageContent} />
        ))}
      </div>
    </div>
  )
}



export function AssistantDetails({ message }: { message: ChatMessage }) {
  return <>
    {message.execution_trace && <TracePanel trace={message.execution_trace} />}
    {message.content && <MarkdownAnswer content={message.content} />}
    {message.generatedFiles && message.generatedFiles.length > 0 && (
      <GeneratedFilesList files={message.generatedFiles} messageContent={message.content} />
    )}
    {message.sources_used && <SourcesButton sources={message.sources_used} />}
    {message.audioUrl && <audio className="panel-enter mt-4 h-9 w-full max-w-sm" controls preload="metadata" src={message.audioUrl} aria-label="Assistant audio reply" />}
  </>
}

