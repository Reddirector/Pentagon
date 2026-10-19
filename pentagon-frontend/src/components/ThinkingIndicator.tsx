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
    <div className="flex items-center gap-2.5 py-1 text-small text-zinc-500" aria-live="polite">
      <span className="flex shrink-0 items-center justify-center" aria-hidden="true">
        <Logomark size={17} loading={true} className="text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.45)]" />
      </span>
      <span className="text-zinc-400 font-medium">{label}</span>
      <span className="tabular-nums text-zinc-600">{formatElapsed(elapsed)}</span>
      {slow ? (
        <span className="truncate text-zinc-600">
          · reasoning models can take a few minutes on the first token
        </span>
      ) : null}
      <span className="sr-only">{model} is working on your request.</span>
    </div>
  )
}