import { Children, isValidElement, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { AlertCircle, Check, CheckCircle2, ChevronDown, CircleDashed, Copy, ExternalLink, FileText, Image as ImageIcon, Layers, Video, X } from 'lucide-react'
import type { ChatMessage, ExecutionTrace, SourcesUsed, TraceEntry } from '../types'

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

const markdownComponents: Components = {
  h1: ({ children }) => <h1 className="mb-3 mt-6 text-xl font-semibold text-white">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-5 text-lg font-semibold text-white">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold text-white">{children}</h3>,
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 ml-5 list-disc space-y-1 marker:text-emerald-400">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 ml-5 list-decimal space-y-1 marker:text-emerald-400">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-emerald-400/60 pl-4 text-zinc-400">{children}</blockquote>,
  a: ({ href, children }) => {
    const url = safeExternalUrl(href)
    return url ? <a href={url} target="_blank" rel="noreferrer" className="text-emerald-300 underline decoration-emerald-300/30 underline-offset-4 hover:text-emerald-200">{children}<ExternalLink className="ml-1 inline" size={11} /></a> : <span>{children}</span>
  },
  code: ({ className, children }) => <code className={className ? 'font-mono text-[.92em] text-emerald-200' : 'rounded bg-white/[0.07] px-1.5 py-0.5 font-mono text-[.9em] text-emerald-200'}>{children}</code>,
  pre: ({ children }) => {
    const first = Children.toArray(children).find(isValidElement)
    const props = first && isValidElement<{ className?: string; children?: ReactNode }>(first) ? first.props : undefined
    const language = props?.className?.replace(/^language-/, '') || ''
    const source = textFromNode(children).replace(/\n$/, '')
    return <CodePanel code={source} language={language}>{children}</CodePanel>
  },
  table: ({ children }) => <div className="my-4 overflow-x-auto"><table className="w-full border-collapse text-left text-sm">{children}</table></div>,
  th: ({ children }) => <th className="border-b border-white/10 px-3 py-2 font-medium text-zinc-300">{children}</th>,
  td: ({ children }) => <td className="border-b border-white/[0.06] px-3 py-2 text-zinc-400">{children}</td>,
  hr: () => <hr className="my-5 border-white/[0.08]" />,
}

function safeExternalUrl(value: string | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null
  } catch { return null }
}

export function MarkdownAnswer({ content }: { content: string }) {
  return <div className="markdown-content min-w-0 break-words text-title leading-[1.8] text-[#d8d9dc]">
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={markdownComponents}>{content}</ReactMarkdown>
  </div>
}

const TRACE_TITLES: Record<string, string> = {
  intent_router: 'Request routing',
  web_search: 'Web search',
  retrieve_documents: 'Retrieved documents',
  vision_analysis: 'Vision analysis',
  context_assembler: 'Context assembly',
  generate_response: 'Model response',
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

export function AssistantDetails({ message }: { message: ChatMessage }) {
  return <>
    {message.execution_trace && <TracePanel trace={message.execution_trace} />}
    <MarkdownAnswer content={message.content} />
    {message.sources_used && <SourcesButton sources={message.sources_used} />}
    {message.audioUrl && <audio className="panel-enter mt-4 h-9 w-full max-w-sm" controls preload="metadata" src={message.audioUrl} aria-label="Assistant audio reply" />}
  </>
}
