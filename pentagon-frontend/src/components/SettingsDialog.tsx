import { useEffect, useRef } from 'react'
import { MoonStar, Sun, Waves, X } from 'lucide-react'
import { getAmbientMode, setAmbientMode, subscribeAmbient } from '../lib/ambient'
import type { AmbientMode } from '../lib/ambient'
import { useSyncExternalStore } from 'react'

const OPTIONS: { mode: AmbientMode; label: string; description: string; icon: typeof Sun }[] = [
  {
    mode: 'full',
    label: 'Full',
    description: 'Aurora, orbit rings, a twinkling constellation, grain and a vignette.',
    icon: Sun,
  },
  { mode: 'calm', label: 'Calm', description: 'Half the stars, slower drift, no long rotations.', icon: Waves },
  { mode: 'off', label: 'Off', description: 'A plain static background. Nothing moves.', icon: MoonStar },
]

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const mode = useSyncExternalStore(subscribeAmbient, getAmbientMode)
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    dialogRef.current?.focus()
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        className="panel-enter w-full max-w-[480px] overflow-hidden rounded-2xl border border-white/[0.1] bg-[#101010]/97 shadow-[0_40px_120px_rgba(0,0,0,.6)] outline-none"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
          <h2 className="text-[13px] font-semibold tracking-[-.01em] text-zinc-100">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-lg p-1 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <X size={15} />
          </button>
        </div>

        <section className="px-5 py-5">
          <h3 className="text-[10px] font-medium uppercase tracking-[.16em] text-zinc-500">Ambient effects</h3>
          <p className="mt-1.5 text-[11px] leading-5 text-zinc-600">
            The background reacts quietly to what Pentagon is doing. Turn it down if you prefer a still
            room.
          </p>
          <div role="radiogroup" aria-label="Ambient background intensity" className="mt-4 grid gap-2">
            {OPTIONS.map((option) => {
              const Icon = option.icon
              const selected = mode === option.mode
              return (
                <button
                  key={option.mode}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setAmbientMode(option.mode)}
                  className={`flex items-start gap-3 rounded-xl border px-3.5 py-3 text-left transition ${
                    selected
                      ? 'border-emerald-300/25 bg-emerald-300/[0.06]'
                      : 'border-white/[0.07] bg-white/[0.02] hover:border-white/[0.12]'
                  }`}
                >
                  <Icon size={15} className={`mt-0.5 shrink-0 ${selected ? 'text-emerald-300' : 'text-zinc-600'}`} />
                  <span className="min-w-0">
                    <span className={`block text-[12px] font-medium ${selected ? 'text-zinc-100' : 'text-zinc-300'}`}>
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-[10px] leading-4 text-zinc-600">{option.description}</span>
                  </span>
                  <span
                    aria-hidden="true"
                    className={`ml-auto mt-1 size-3.5 shrink-0 rounded-full border ${
                      selected ? 'border-emerald-300 bg-emerald-300/80' : 'border-white/[0.18]'
                    }`}
                  />
                </button>
              )
            })}
          </div>
        </section>
      </div>
    </div>
  )
}