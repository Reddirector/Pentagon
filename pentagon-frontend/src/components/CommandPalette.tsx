import { useEffect, useMemo, useRef, useState } from 'react'
import { FileText, Gauge, MoonStar, Plus, Search, Sun, Waves } from 'lucide-react'
import { getAmbientMode, setAmbientMode } from '../lib/ambient'
import type { AmbientMode } from '../lib/ambient'

type Command = {
  id: string
  label: string
  hint?: string
  keywords: string
  run: () => void
}

const AMBIENT_OPTIONS: { mode: AmbientMode; label: string; icon: typeof Sun }[] = [
  { mode: 'full', label: 'Ambient: Full', icon: Sun },
  { mode: 'calm', label: 'Ambient: Calm', icon: Waves },
  { mode: 'off', label: 'Ambient: Off', icon: MoonStar },
]

export function CommandPalette({
  onNewThread,
  onFocusSearch,
  onToggleWebSearch,
  onClose,
}: {
  onNewThread: () => void
  onFocusSearch: () => void
  onToggleWebSearch: () => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const commands = useMemo<Command[]>(() => {
    const ambient = AMBIENT_OPTIONS.map((option) => ({
      id: `ambient-${option.mode}`,
      label: option.label,
      hint: getAmbientMode() === option.mode ? 'current' : undefined,
      keywords: `ambient background effects ${option.mode}`,
      run: () => setAmbientMode(option.mode),
    }))
    return [
      { id: 'new', label: 'New thread', keywords: 'chat conversation start', run: onNewThread },
      { id: 'search', label: 'Search conversations', keywords: 'find filter threads', run: onFocusSearch },
      { id: 'web', label: 'Toggle web search', keywords: 'internet retrieval grounded', run: onToggleWebSearch },
      ...ambient,
    ]
  }, [onNewThread, onFocusSearch, onToggleWebSearch])

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return commands
    return commands.filter((command) =>
      `${command.label} ${command.keywords}`.toLowerCase().includes(needle),
    )
  }, [commands, query])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Clamp at the point of use so a shrinking result list can never leave the
  // highlight pointing past the end.
  const activeIndex = Math.min(highlight, Math.max(0, results.length - 1))

  function runCommand(command: Command) {
    command.run()
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[14vh] backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="panel-enter w-full max-w-[520px] overflow-hidden rounded-2xl border border-white/[0.1] bg-[#14161a]/97 shadow-[0_40px_120px_rgba(0,0,0,.6)] focus-within:border-emerald-300/25"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-white/[0.07] px-4">
          <Search size={15} className="shrink-0 text-zinc-500" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') onClose()
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setHighlight((value) => (results.length ? (value + 1) % results.length : 0))
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault()
                setHighlight((value) =>
                  results.length ? (value - 1 + results.length) % results.length : 0,
                )
              }
              if (event.key === 'Enter' && results[activeIndex]) {
                event.preventDefault()
                runCommand(results[activeIndex])
              }
            }}
            placeholder="Type a command…"
            aria-label="Command palette input"
            className="h-12 w-full bg-transparent text-[13px] text-zinc-100 outline-none focus-visible:outline-none placeholder:text-zinc-600"
          />
          <kbd className="shrink-0 rounded-md border border-white/[0.09] px-1.5 py-0.5 text-[9px] text-zinc-500">
            esc
          </kbd>
        </div>

        <ul className="max-h-[46vh] overflow-y-auto py-1.5">
          {results.map((command, index) => {
            const Icon =
              command.id === 'new'
                ? Plus
                : command.id === 'search'
                  ? Search
                  : command.id === 'web'
                    ? Gauge
                    : AMBIENT_OPTIONS.find((option) => command.id === `ambient-${option.mode}`)?.icon ??
                      FileText
            return (
              <li key={command.id}>
                <button
                  type="button"
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => runCommand(command)}
                  className={`flex w-full items-center gap-3 px-4 py-2.5 text-left text-[12px] transition ${
                    index === activeIndex
                      ? 'bg-emerald-300/[0.09] text-zinc-100'
                      : 'text-zinc-400 hover:bg-white/[0.04]'
                  }`}
                >
                  <Icon size={14} className="shrink-0 text-zinc-500" />
                  <span className="flex-1 truncate">{command.label}</span>
                  {command.hint ? (
                    <span className="shrink-0 text-[9px] uppercase tracking-[.16em] text-emerald-300/70">
                      {command.hint}
                    </span>
                  ) : null}
                </button>
              </li>
            )
          })}
          {results.length === 0 ? (
            <li className="px-4 py-6 text-center text-[11px] text-zinc-600">No matching command.</li>
          ) : null}
        </ul>
      </div>
    </div>
  )
}