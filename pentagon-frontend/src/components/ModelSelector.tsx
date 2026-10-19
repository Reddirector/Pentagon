/**
 * ModelSelector: Polished, modern model selector dropdown.
 * Replaces the raw OS native select with a clean, searchable, capability-rich popover.
 */
import { useEffect, useId, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  Cpu,
  ImageIcon,
  LoaderCircle,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import type { ModelInfo } from '../types'

export function ModelSelector({
  models,
  selectedModel,
  onSelectModel,
  disabled = false,
  switching = false,
  agentBadge,
}: {
  models: ModelInfo[]
  selectedModel: string
  onSelectModel: (modelId: string) => void
  disabled?: boolean
  switching?: boolean
  agentBadge?: string
}) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const searchId = useId()

  const activeModel = models.find((m) => m.id === selectedModel)

  const close = () => {
    setOpen(false)
    setFilter('')
  }

  // Focus search input when opened
  useEffect(() => {
    if (open) {
      const timer = window.setTimeout(() => searchInputRef.current?.focus(), 50)
      return () => window.clearTimeout(timer)
    }
  }, [open])

  // Click outside and escape handling
  useEffect(() => {
    if (!open) return

    const handlePointerDown = (event: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        close()
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }

    window.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  const filteredModels = models.filter((m) =>
    m.id.toLowerCase().includes(filter.trim().toLowerCase())
  )

  // Format model display name for cleaner reading
  function formatModelName(id: string) {
    if (!id) return 'Select a model'
    // E.g. meta/llama-3.3-70b-instruct -> llama-3.3-70b-instruct
    const parts = id.split('/')
    return parts[parts.length - 1]
  }

  function getModelFamily(id: string) {
    if (id.includes('llama')) return 'Llama'
    if (id.includes('deepseek')) return 'DeepSeek'
    if (id.includes('mixtral') || id.includes('mistral')) return 'Mistral'
    if (id.includes('nemotron')) return 'Nemotron'
    if (id.includes('gpt') || id.includes('openai')) return 'OpenAI'
    if (id.includes('qwen')) return 'Qwen'
    if (id.includes('gemma')) return 'Gemma'
    return 'LLM'
  }

  return (
    <div ref={containerRef} className="relative">
      {/* Trigger Button */}
      <button
        type="button"
        disabled={disabled || !models.length}
        onClick={() => {
          setOpen((prev) => {
            if (prev) setFilter('')
            return !prev
          })
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`group flex h-9 max-w-[135px] xs:max-w-[190px] sm:max-w-[min(48vw,420px)] lg:max-w-[min(38vw,420px)] items-center gap-1.5 sm:gap-2 rounded-xl border px-2 sm:px-2.5 text-left transition ${
          open
            ? 'border-emerald-500/40 bg-emerald-500/[0.08] shadow-[0_0_12px_rgba(16,185,129,0.15)]'
            : 'border-white/[0.1] bg-white/[0.035] hover:border-white/[0.18] hover:bg-white/[0.06]'
        } disabled:cursor-not-allowed disabled:opacity-40`}
      >
        <div className="grid size-5 shrink-0 place-items-center rounded-lg bg-emerald-400/10 text-emerald-300">
          <Sparkles size={12} />
        </div>

        <div className="min-w-0 flex-1 truncate text-small font-medium text-zinc-100">
          {switching ? (
            <span className="flex items-center gap-1.5 text-zinc-400">
              <LoaderCircle size={12} className="animate-spin text-emerald-400" />
              <span className="truncate">Switching…</span>
            </span>
          ) : (
            <span className="truncate">{formatModelName(selectedModel)}</span>
          )}
        </div>

        {activeModel?.supports_vision && (
          <span
            title="Vision supported"
            className="hidden items-center gap-1 rounded-md border border-violet-400/20 bg-violet-400/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-300 sm:inline-flex"
          >
            <ImageIcon size={10} />
            <span className="max-md:hidden">Vision</span>
          </span>
        )}

        {agentBadge && (
          <span
            title={agentBadge}
            className="hidden items-center gap-1 rounded-md border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300 sm:inline-flex"
          >
            <ShieldCheck size={10} />
            <span className="max-md:hidden">{agentBadge}</span>
          </span>
        )}

        <ChevronDown
          size={13}
          className={`shrink-0 text-zinc-400 transition-transform duration-150 ${
            open ? 'rotate-180 text-zinc-200' : ''
          }`}
        />
      </button>

      {/* Dropdown Popover */}
      {open && (
        <div
          role="listbox"
          aria-label="Select AI model"
          className="fixed sm:absolute inset-x-3 sm:inset-x-auto sm:left-0 top-[64px] sm:top-[calc(100%+8px)] z-50 flex max-h-[75vh] w-auto sm:w-[min(92vw,440px)] flex-col rounded-2xl border border-white/[0.12] bg-[#0c0c0c]/95 p-2 shadow-[0_24px_60px_rgba(0,0,0,0.85)] backdrop-blur-2xl ring-1 ring-white/[0.05] animate-in fade-in zoom-in-95"
        >
          {/* Header & Search */}
          <div className="border-b border-white/[0.07] p-2 pb-2.5">
            <div className="mb-2 flex items-center justify-between text-caption font-semibold uppercase tracking-wider text-zinc-400">
              <span>NVIDIA NIM Models</span>
              <span className="font-mono text-[10px] text-zinc-500">
                {models.length} {models.length === 1 ? 'model' : 'models'}
              </span>
            </div>

            {models.length > 4 && (
              <div className="relative">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500" />
                <input
                  ref={searchInputRef}
                  id={searchId}
                  type="text"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Filter models..."
                  className="h-8 w-full rounded-lg border border-white/[0.08] bg-white/[0.03] pl-8 pr-2.5 text-small text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-emerald-400/30 focus:bg-white/[0.05]"
                />
              </div>
            )}
          </div>

          {/* Model Items List */}
          <div className="max-h-[340px] overflow-y-auto space-y-1 py-1.5">
            {filteredModels.length === 0 ? (
              <div className="p-4 text-center text-small text-zinc-500">
                No matching models found.
              </div>
            ) : (
              filteredModels.map((model) => {
                const isSelected = model.id === selectedModel
                const family = getModelFamily(model.id)
                return (
                  <button
                    key={model.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      close()
                      if (!isSelected) onSelectModel(model.id)
                    }}
                    className={`group flex w-full items-start gap-2.5 rounded-xl p-2.5 text-left transition ${
                      isSelected
                        ? 'border border-emerald-500/25 bg-emerald-500/[0.1] text-white'
                        : 'border border-transparent text-zinc-300 hover:border-white/[0.06] hover:bg-white/[0.04] hover:text-white'
                    }`}
                  >
                    <div
                      className={`grid size-7 shrink-0 place-items-center rounded-lg border ${
                        isSelected
                          ? 'border-emerald-400/30 bg-emerald-400/20 text-emerald-300'
                          : 'border-white/[0.08] bg-white/[0.03] text-zinc-500 group-hover:text-zinc-300'
                      }`}
                    >
                      <Cpu size={13} />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-small font-medium">{model.id}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <span className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-zinc-400">
                          {family}
                        </span>
                        {model.supports_vision && (
                          <span className="flex items-center gap-1 rounded border border-violet-400/20 bg-violet-400/10 px-1.5 py-0.5 text-[9px] font-medium text-violet-300">
                            <ImageIcon size={9} /> Vision
                          </span>
                        )}
                        {model.context_window && (
                          <span className="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[9px] text-zinc-500">
                            {Math.round(model.context_window / 1024)}k ctx
                          </span>
                        )}
                      </div>
                    </div>

                    {isSelected && (
                      <div className="mt-0.5 shrink-0 text-emerald-400">
                        <Check size={14} />
                      </div>
                    )}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
