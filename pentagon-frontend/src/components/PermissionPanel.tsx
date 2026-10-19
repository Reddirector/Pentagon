import { useState } from 'react'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Eye,
  FileEdit,
  Globe,
  Lock,
  Shield,
  ShieldAlert,
  Terminal,
  Trash2,
} from 'lucide-react'
import type { AutonomySettings } from '../types'

/**
 * The permissions panel.
 *
 * Six rows, one per risk category, each with a responsive 4-level segmented
 * control across the autonomy levels.
 *
 * Above the rows: a preset switcher that sets a baseline across all six.
 * Below: a collapsible granular per-tool overrides section.
 */

const LEVEL_KEYS = ['always_ask', 'ask_first_time', 'auto_approve', 'never_allow'] as const

function getCategoryMeta(category: string) {
  switch (category) {
    case 'read_only_info':
      return {
        Icon: Eye,
        badgeLabel: 'Read Only',
        badgeClass: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400',
        tagClass: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
      }
    case 'local_filesystem_write':
      return {
        Icon: FileEdit,
        badgeLabel: 'Local Files',
        badgeClass: 'border-blue-500/20 bg-blue-500/10 text-blue-400',
        tagClass: 'border-blue-500/20 bg-blue-500/10 text-blue-300',
      }
    case 'local_shell':
      return {
        Icon: Terminal,
        badgeLabel: 'Shell Commands',
        badgeClass: 'border-amber-500/20 bg-amber-500/10 text-amber-400',
        tagClass: 'border-amber-500/20 bg-amber-500/10 text-amber-300',
      }
    case 'external_write':
      return {
        Icon: Globe,
        badgeLabel: 'External Services',
        badgeClass: 'border-indigo-500/20 bg-indigo-500/10 text-indigo-400',
        tagClass: 'border-indigo-500/20 bg-indigo-500/10 text-indigo-300',
      }
    case 'external_destructive':
      return {
        Icon: Trash2,
        badgeLabel: 'Destructive',
        badgeClass: 'border-rose-500/20 bg-rose-500/10 text-rose-400',
        tagClass: 'border-rose-500/20 bg-rose-500/10 text-rose-300',
      }
    case 'financial_or_irreversible':
      return {
        Icon: Lock,
        badgeLabel: 'Irreversible',
        badgeClass: 'border-purple-500/20 bg-purple-500/10 text-purple-400',
        tagClass: 'border-purple-500/20 bg-purple-500/10 text-purple-300',
      }
    default:
      return {
        Icon: Shield,
        badgeLabel: category.replace(/_/g, ' '),
        badgeClass: 'border-white/[0.08] bg-white/[0.04] text-zinc-400',
        tagClass: 'border-white/[0.08] bg-white/[0.04] text-zinc-300',
      }
  }
}

export function PermissionPanel({
  settings,
  busy = false,
  onChange,
  onPresetChange,
  onOverrideToggle,
}: {
  settings: AutonomySettings
  busy?: boolean
  onChange: (category: string, level: string) => void | Promise<void>
  onPresetChange?: (preset: string) => void | Promise<void>
  onOverrideToggle?: (toolName: string, enabled: boolean) => void | Promise<void>
}) {
  const [overridesOpen, setOverridesOpen] = useState(false)

  const effectiveLevel = (category: string): string | null => {
    const explicit = settings.settings[category]
    if (explicit) return explicit
    if (settings.defaults[category]) return settings.defaults[category]
    return null
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      {/* Preset switcher */}
      {onPresetChange && settings.presets && (
        <fieldset className="space-y-2">
          <legend className="sr-only">Autonomy preset</legend>
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3.5 sm:p-4 transition hover:border-white/[0.12]">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="grid size-8 shrink-0 place-items-center rounded-lg border border-emerald-500/20 bg-emerald-500/10 text-emerald-400">
                  <Shield size={16} />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-small font-semibold text-zinc-100">Autonomy Preset</span>
                    <span className="rounded-md border border-white/[0.08] bg-white/[0.05] px-2 py-0.5 text-micro font-medium uppercase tracking-wider text-zinc-300">
                      {settings.preset || 'Custom'}
                    </span>
                  </div>
                  <p className="mt-0.5 text-micro text-zinc-400">
                    Apply a recommended baseline across all six risk categories
                  </p>
                </div>
              </div>

              {/* Segmented Preset Buttons */}
              <div
                role="radiogroup"
                aria-label="Autonomy preset"
                className="grid grid-cols-3 gap-1 rounded-xl border border-white/[0.08] bg-black/40 p-1 sm:w-auto"
              >
                {Object.values(settings.presets).map((preset) => {
                  const selected = settings.preset === preset.name
                  return (
                    <button
                      key={preset.name}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={busy}
                      onClick={() => void onPresetChange(preset.name)}
                      title={preset.description}
                      className={`flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-caption font-medium transition ${
                        selected
                          ? 'border border-emerald-500/30 bg-emerald-500/20 text-emerald-200 shadow-sm'
                          : 'border border-transparent text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200'
                      } ${busy ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
                    >
                      {selected && <Check size={11} className="text-emerald-400" />}
                      <span>{preset.name}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </fieldset>
      )}

      {/* Six category rows */}
      <fieldset className="space-y-2.5">
        <legend className="sr-only">Risk-category autonomy</legend>
        {settings.categories &&
          Object.entries(settings.categories).map(([category, meta]) => {
            const current = effectiveLevel(category)
            const catMeta = getCategoryMeta(category)
            const CatIcon = catMeta.Icon

            return (
              <div
                key={category}
                className={`rounded-xl border border-white/[0.08] bg-white/[0.015] p-3.5 sm:p-4 transition hover:border-white/[0.12] hover:bg-white/[0.025] ${
                  busy ? 'cursor-not-allowed opacity-60' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <div
                      className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border ${catMeta.badgeClass}`}
                    >
                      <CatIcon size={15} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-body-sm font-semibold text-zinc-100">{meta.label}</span>
                        <span
                          className={`rounded border px-1.5 py-0.5 text-micro font-medium uppercase tracking-wider ${catMeta.tagClass}`}
                        >
                          {catMeta.badgeLabel}
                        </span>
                      </div>
                      <p className="mt-1 text-small leading-relaxed text-zinc-400">{meta.description}</p>
                    </div>
                  </div>
                </div>

                {/* 4-column Segmented Level Grid */}
                <div
                  className="mt-3.5 grid grid-cols-2 sm:grid-cols-4 gap-1.5 sm:gap-2"
                  role="radiogroup"
                  aria-label={`${meta.label} autonomy level`}
                >
                  {LEVEL_KEYS.map((key) => {
                    const lbl = settings.levels?.[key]?.label ?? key
                    const sel = current === key
                    const isBlock = key === 'never_allow'

                    return (
                      <button
                        key={key}
                        type="button"
                        role="radio"
                        aria-checked={sel}
                        disabled={busy || !settings.available}
                        onClick={() => {
                          if (current !== key) void onChange(category, key)
                        }}
                        title={settings.levels?.[key]?.description ?? lbl}
                        className={`flex h-8 sm:h-9 items-center justify-center gap-1.5 rounded-lg border px-2 text-caption font-medium transition ${
                          sel
                            ? isBlock
                              ? 'border-rose-500/40 bg-rose-500/10 text-rose-200 shadow-[0_0_12px_rgba(244,63,94,0.15)]'
                              : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
                            : 'border-white/[0.07] bg-white/[0.02] text-zinc-400 hover:border-white/[0.14] hover:bg-white/[0.05] hover:text-zinc-200'
                        } ${busy || !settings.available ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                      >
                        {sel && (
                          <Check
                            size={11}
                            className={isBlock ? 'text-rose-400 shrink-0' : 'text-emerald-400 shrink-0'}
                          />
                        )}
                        <span className="truncate">{lbl}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
      </fieldset>

      {!settings.available && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.04] p-3.5 text-small leading-relaxed text-amber-200/90">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-400" />
          <span>
            The permission system is switched off on this server, so tools currently operate under server defaults.
          </span>
        </div>
      )}

      {/* Advanced: per-tool overrides */}
      {settings.tools && settings.tools.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.015]">
          <button
            type="button"
            className={`flex w-full items-center justify-between gap-2.5 bg-white/[0.02] px-4 py-3 text-small font-medium text-zinc-300 transition hover:bg-white/[0.04] ${
              overridesOpen ? 'border-b border-white/[0.07]' : ''
            }`}
            onClick={() => setOverridesOpen((v) => !v)}
            aria-expanded={overridesOpen}
          >
            <div className="flex items-center gap-2">
              {overridesOpen ? (
                <ChevronDown size={14} className="text-zinc-400" />
              ) : (
                <ChevronRight size={14} className="text-zinc-400" />
              )}
              <span>Advanced: Per-Tool Overrides</span>
            </div>
            <span className="rounded-full bg-white/[0.08] px-2 py-0.5 text-caption font-medium text-zinc-400">
              {settings.tools.length} {settings.tools.length === 1 ? 'tool' : 'tools'}
            </span>
          </button>
          {overridesOpen && (
            <div className="p-3.5 space-y-2">
              {settings.tools.length === 0 ? (
                <p className="text-small text-zinc-500">No registered tools found.</p>
              ) : (
                <ul className="space-y-1.5">
                  {settings.tools.map((tool) => {
                    const inherited = tool.category
                      ? settings.categories?.[tool.category]?.label ?? tool.category
                      : null
                    return (
                      <li
                        key={tool.name}
                        className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="text-small font-medium text-zinc-200">{tool.name}</span>
                          <span className="ml-2 rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-micro text-zinc-400">
                            {inherited ?? 'unknown'}
                          </span>
                        </span>
                        {onOverrideToggle && (
                          <button
                            type="button"
                            role="switch"
                            aria-checked={!!tool.overrideEnabled}
                            disabled={busy}
                            onClick={() => void onOverrideToggle(tool.name, !tool.overrideEnabled)}
                            className={`shrink-0 rounded-lg border px-2.5 py-1 text-caption font-medium transition ${
                              tool.overrideEnabled
                                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                                : 'border-white/[0.08] bg-white/[0.02] text-zinc-400 hover:border-white/[0.14] hover:text-zinc-200'
                            } ${busy ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
                          >
                            {tool.overrideEnabled ? 'Override on' : 'Inherit'}
                          </button>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* Safety Guarantee Footer */}
      <div className="flex items-start gap-3 rounded-xl border border-white/[0.08] bg-white/[0.02] p-3.5 text-caption leading-relaxed text-zinc-400">
        <ShieldAlert size={16} className="mt-0.5 shrink-0 text-emerald-400" />
        <p>
          <strong className="font-medium text-zinc-200">Safety Guarantee:</strong> High-risk operations—such as executing arbitrary commands, deleting non-recoverable assets, or financial transactions—always pause for explicit user confirmation before running, regardless of your chosen autonomy level.
        </p>
      </div>
    </div>
  )
}