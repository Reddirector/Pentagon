import { useEffect, useState } from 'react'
import { Logomark } from './Logomark'

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`
}

/**
 * Reasoning models (e.g. z-ai/glm-5.3-flash) can take 2-3 minutes before their
 * first token, which reads as a dead UI. Showing elapsed time turns a silent
 * wait into a legible one.
 *
 * Mounted only while a turn is genuinely in flight, so the elapsed clock starts
 * at the moment the wait begins.
 */
export function ThinkingIndicator({ model, label = 'Thinking' }: { model: string; label?: string }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const slow = elapsed >= 20

  return (
    <div
      className="inline-flex items-center gap-2.5 rounded-full border border-emerald-500/20 bg-[#090e13]/80 px-3.5 py-1.5 text-small text-zinc-400 backdrop-blur-md shadow-[0_0_20px_rgba(52,211,153,0.12)] transition-all duration-300"
      aria-live="polite"
    >
      <span className="flex shrink-0 items-center justify-center" aria-hidden="true">
        <Logomark size={16} loading={true} className="text-emerald-400 drop-shadow-[0_0_10px_rgba(52,211,153,0.6)]" />
      </span>
      <span className="thinking-shimmer font-semibold tracking-wide text-xs">
        {label}
      </span>
      <div className="flex items-center gap-1 px-0.5" aria-hidden="true">
        <span className="size-1.5 rounded-full bg-emerald-400 synaptic-dot" style={{ animationDelay: '0s' }} />
        <span className="size-1.5 rounded-full bg-emerald-400 synaptic-dot" style={{ animationDelay: '0.35s' }} />
        <span className="size-1.5 rounded-full bg-emerald-400 synaptic-dot" style={{ animationDelay: '0.7s' }} />
      </div>
      <span className="tabular-nums font-mono text-[11px] text-emerald-400/80 bg-emerald-400/10 px-1.5 py-0.5 rounded-md">
        {formatElapsed(elapsed)}
      </span>
      {slow ? (
        <span className="truncate text-emerald-400/80 text-[11px] max-w-[240px] sm:max-w-none animate-pulse">
          · {elapsed >= 35 ? 'large model reasoning (may take 1–2 min)' : 'deep reasoning in progress'}
        </span>
      ) : null}
      <span className="sr-only">{model} is working on your request.</span>
    </div>
  )
}