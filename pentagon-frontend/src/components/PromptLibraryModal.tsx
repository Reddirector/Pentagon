import { useState, useMemo } from 'react'
import {
  Check,
  Copy,
  Search,
  Sparkles,
  Wand2,
  X,
} from 'lucide-react'
import { SCALED_PROMPTS, type ScaledPrompt } from '../lib/scaledPrompts'

interface PromptLibraryModalProps {
  isOpen: boolean
  onClose: () => void
  onSelectPrompt: (promptText: string) => void
}

export function PromptLibraryModal({
  isOpen,
  onClose,
  onSelectPrompt,
}: PromptLibraryModalProps) {
  const [selectedCategory, setSelectedCategory] = useState<string>('All')
  const [searchQuery, setSearchQuery] = useState('')
  const [activePrompt, setActivePrompt] = useState<ScaledPrompt>(SCALED_PROMPTS[0])
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState(false)

  const categories = ['All', 'Coding', 'Reasoning', 'Product', 'Systems']

  const filteredPrompts = useMemo(() => {
    return SCALED_PROMPTS.filter((p) => {
      const matchesCat = selectedCategory === 'All' || p.category === selectedCategory
      const matchesQuery =
        p.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.tags.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()))
      return matchesCat && matchesQuery
    })
  }, [selectedCategory, searchQuery])

  // Compute interpolated prompt text
  const interpolatedPrompt = useMemo(() => {
    if (!activePrompt) return ''
    let text = activePrompt.template
    if (activePrompt.parameters) {
      for (const param of activePrompt.parameters) {
        const val = paramValues[param.key] || param.defaultValue || `[${param.label}]`
        text = text.replaceAll(`{{${param.key}}}`, val)
      }
    }
    return text
  }, [activePrompt, paramValues])

  const handleUsePrompt = () => {
    onSelectPrompt(interpolatedPrompt)
    onClose()
  }

  const handleCopyPrompt = async () => {
    await navigator.clipboard.writeText(interpolatedPrompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative flex h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-white/[0.1] bg-[#0c0c0f] shadow-[0_25px_80px_rgba(0,0,0,0.8)]">
        {/* Modal Header */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.08] bg-[#121216] px-5">
          <div className="flex items-center gap-2.5">
            <div className="grid size-8 place-items-center rounded-lg border border-amber-500/25 bg-amber-500/10 text-amber-400">
              <Sparkles size={16} />
            </div>
            <div>
              <h2 className="text-small font-semibold text-zinc-100 flex items-center gap-2">
                Scaled Prompts Library
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-mono text-amber-300">
                  Claude-Grade
                </span>
              </h2>
              <p className="text-[11px] text-zinc-400">
                Battle-tested prompt engineering templates for deep engineering, artifacts &amp; analysis.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
          >
            <X size={15} />
          </button>
        </header>

        {/* Search & Filter Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] bg-[#0f0f13] px-5 py-2.5">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search prompts, tags, or concepts..."
              className="w-full rounded-lg border border-white/[0.08] bg-black/40 pl-9 pr-3 py-1.5 text-micro text-zinc-200 placeholder:text-zinc-500 outline-none focus:border-amber-500/40"
            />
          </div>

          <div className="flex items-center gap-1.5 overflow-x-auto">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setSelectedCategory(cat)}
                className={`rounded-lg px-2.5 py-1 text-micro font-medium transition ${
                  selectedCategory === cat
                    ? 'bg-amber-500/20 text-amber-200 border border-amber-500/30'
                    : 'text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* Two-Column Body */}
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          {/* Left Column: Prompt Cards List */}
          <div className="w-full md:w-80 lg:w-96 shrink-0 overflow-y-auto border-r border-white/[0.08] bg-[#0c0c0f] p-3 space-y-2">
            {filteredPrompts.map((p) => {
              const isSelected = activePrompt?.id === p.id
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    setActivePrompt(p)
                    setParamValues({})
                  }}
                  className={`w-full rounded-xl border p-3 text-left transition-all ${
                    isSelected
                      ? 'border-amber-500/40 bg-amber-500/[0.08] shadow-sm'
                      : 'border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.04]'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-micro font-semibold text-zinc-200 truncate">{p.title}</span>
                    <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[9px] uppercase font-mono text-amber-300/80 shrink-0">
                      {p.category}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-zinc-400">
                    {p.description}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {p.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full bg-white/[0.04] px-2 py-0.5 text-[9px] text-zinc-400 font-mono"
                      >
                        #{tag}
                      </span>
                    ))}
                  </div>
                </button>
              )
            })}
          </div>

          {/* Right Column: Prompt Customizer & Preview */}
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-[#0a0a0d] p-5">
            {activePrompt && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">{activePrompt.title}</h3>
                  <p className="text-caption text-zinc-400 mt-0.5">{activePrompt.description}</p>
                </div>

                {/* Parameters configuration */}
                {activePrompt.parameters && activePrompt.parameters.length > 0 && (
                  <div className="rounded-xl border border-white/[0.08] bg-black/40 p-4 space-y-3">
                    <h4 className="text-micro font-semibold text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
                      <Wand2 size={12} />
                      Customize Prompt Parameters
                    </h4>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {activePrompt.parameters.map((param) => (
                        <div key={param.key} className="space-y-1">
                          <label className="text-[11px] font-medium text-zinc-300">
                            {param.label}
                          </label>
                          <input
                            type="text"
                            value={paramValues[param.key] || ''}
                            onChange={(e) =>
                              setParamValues((prev) => ({ ...prev, [param.key]: e.target.value }))
                            }
                            placeholder={param.placeholder}
                            className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-micro text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-amber-500/40"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Prompt Output Preview */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-micro text-zinc-400 font-mono">
                    <span>Generated Prompt Preview:</span>
                    <span>{interpolatedPrompt.length} chars</span>
                  </div>
                  <pre className="max-h-72 overflow-y-auto rounded-xl border border-white/[0.08] bg-black/60 p-4 font-mono text-[12px] leading-relaxed text-zinc-300 whitespace-pre-wrap select-text">
                    {interpolatedPrompt}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Modal Footer Actions */}
        <footer className="flex h-14 shrink-0 items-center justify-between border-t border-white/[0.08] bg-[#121216] px-5">
          <div className="text-caption text-zinc-500 font-mono">
            {activePrompt?.parameters?.length ? 'Parameters auto-substituted' : 'Ready to use'}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopyPrompt}
              className="flex items-center gap-1.5 rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 py-1.5 text-micro font-medium text-zinc-200 transition hover:bg-white/[0.08] hover:text-white"
            >
              {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
            <button
              type="button"
              onClick={handleUsePrompt}
              className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-amber-500 to-amber-600 px-4 py-1.5 text-micro font-semibold text-black transition hover:from-amber-400 hover:to-amber-500 shadow-md shadow-amber-950/40"
            >
              <Sparkles size={13} />
              <span>Use in Chat</span>
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
