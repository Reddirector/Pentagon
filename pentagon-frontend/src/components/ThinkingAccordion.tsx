import { useState } from 'react'
import { Brain, Check, ChevronDown, Copy, Sparkles } from 'lucide-react'

interface ThinkingAccordionProps {
  thinking: string
  isStreaming?: boolean
  durationSeconds?: number
  defaultExpanded?: boolean
}

export function ThinkingAccordion({
  thinking,
  isStreaming = false,
  durationSeconds,
  defaultExpanded = false,
}: ThinkingAccordionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded || isStreaming)
  const [copied, setCopied] = useState(false)

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!thinking) return
    await navigator.clipboard.writeText(thinking)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (!thinking && !isStreaming) return null

  const displayTime = durationSeconds ? `${durationSeconds}s` : 'a few seconds'

  return (
    <div className="my-2.5 overflow-hidden rounded-xl border border-amber-500/15 bg-[#141210]/70 transition-all duration-200 hover:border-amber-500/25">
      {/* Header Bar */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between px-3.5 py-2 text-left text-micro font-medium text-amber-200/80 transition hover:bg-amber-500/[0.04]"
      >
        <div className="flex items-center gap-2">
          {isStreaming ? (
            <span className="relative flex h-3.5 w-3.5 items-center justify-center">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
              <Brain size={13} className="text-amber-400" />
            </span>
          ) : (
            <Brain size={13} className="text-amber-400/90" />
          )}

          <span className="text-caption sm:text-micro tracking-wide text-amber-100/90 font-medium">
            {isStreaming ? 'Thinking...' : `Thought for ${displayTime}`}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {thinking && (
            <button
              type="button"
              onClick={handleCopy}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-amber-200/60 transition hover:bg-amber-500/15 hover:text-amber-200"
              title="Copy thinking tokens"
            >
              {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          )}

          <ChevronDown
            size={13}
            className={`text-amber-400/70 transition-transform duration-200 ${
              expanded ? 'rotate-180' : ''
            }`}
          />
        </div>
      </button>

      {/* Expanded Thought Stream */}
      {expanded && (
        <div className="border-t border-amber-500/10 px-3.5 py-3 bg-black/30">
          <div className="max-h-80 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-zinc-400 scrollbar-thin scrollbar-thumb-zinc-700">
            {thinking || (
              <span className="italic text-zinc-500 flex items-center gap-1.5">
                <Sparkles size={11} className="animate-pulse text-amber-400/60" />
                Processing reasoning pathways...
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
