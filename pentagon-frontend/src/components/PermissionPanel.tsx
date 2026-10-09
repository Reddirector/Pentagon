import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Shield, AlertTriangle } from 'lucide-react'
import type { AutonomySettings } from '../types'

/**
 * The permissions panel.
 *
 * Six rows, one per risk category, each a segmented control across the four
 * autonomy levels. Plain-language labels come from the backend's
 * /api/autonomy-settings response, not from this file.
 *
 * Above the rows: a preset switcher that fills all six at once. Below: a
 * collapsible "Advanced: per-tool overrides" section listing registered tools
 * with their inherited category shown greyed out (v1 wires the list only;
 * true per-tool-level overrides beyond session-approval-memory are a stretch
 * goal not required for v1).
 */

const LEVEL_KEYS = ['always_ask', 'ask_first_time', 'auto_approve', 'never_allow'] as const

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
    <div className="space-y-5">
      {/* Headline */}
      <div>
        <h2 className="text-body font-medium text-zinc-100">Permissions</h2>
        <p className="mt-1 text-small leading-5 text-zinc-500">
          Pentagon sorts every tool call into one of six kinds of action, and you
          choose how each kind behaves: always ask, ask once this session, run
          automatically, or block outright.
        </p>
      </div>

      {/* Preset switcher */}
      {onPresetChange && settings.presets && (
        <fieldset className="space-y-2">
          <legend className="sr-only">Autonomy preset</legend>
          <div className="flex items-center gap-3 rounded-xl border border-white/[0.09] bg-white/[0.02] px-3.5 py-2.5">
            <Shield size={14} className="shrink-0 text-zinc-500" />
            <span className="text-micro font-medium uppercase tracking-[.14em] text-zinc-500">Preset</span>
            <div className="flex gap-1.5" role="radiogroup" aria-label="Autonomy preset">
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
                    className={`rounded-lg border px-2.5 py-1.5 text-small transition ${
                      selected
                        ? 'border-emerald-300/30 bg-emerald-300/[0.06] text-zinc-100'
                        : 'border-white/[0.08] bg-white/[0.02] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300'
                    } ${busy ? 'cursor-not-allowed opacity-60' : ''}`}
                  >
                    {preset.name}
                    {selected && <Check size={11} className="ml-1 text-emerald-300" />}
                  </button>
                )
              })}
            </div>
          </div>
        </fieldset>
      )}

      {/* Six category rows */}
      <fieldset className="space-y-2">
        <legend className="sr-only">Risk-category autonomy</legend>
        {settings.categories && Object.entries(settings.categories).map(([category, meta]) => {
          const current = effectiveLevel(category)
          return (
            <div key={category} className={`rounded-xl border px-3.5 py-3 transition ${busy ? 'cursor-not-allowed opacity-60' : ''}`}
              style={{ borderColor: current ? 'rgba(239,239,239,0.12)' : 'rgba(255,255,255,0.07)' }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className="text-small font-medium text-zinc-100">{meta.label}</span>
                  <span className="mt-1 block text-micro leading-5 text-zinc-500">{meta.description}</span>
                </div>
                <span className="shrink-0 rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-micro text-zinc-500 uppercase tracking-wider">
                  {category}
                </span>
              </div>

              <div className="mt-2.5 flex flex-wrap gap-1.5" role="radiogroup" aria-label={`${meta.label} autonomy level`}>
                {LEVEL_KEYS.map((key) => {
                  const lbl = settings.levels?.[key]?.label ?? key
                  const sel = current === key
                  return (
                    <button
                      key={key}
                      type="button"
                      role="radio"
                      aria-checked={sel}
                      disabled={busy || !settings.available}
                      onClick={() => { if (current !== key) void onChange(category, key) }}
                      className={`rounded-lg border px-2.5 py-1.5 text-small transition ${
                        sel
                          ? 'border-emerald-300/30 bg-emerald-300/[0.06] text-zinc-100'
                          : 'border-white/[0.08] bg-white/[0.02] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300'
                      } ${busy || !settings.available ? 'cursor-not-allowed opacity-60' : ''}`}
                    >
                      {lbl}
                      {sel && <Check size={11} className="ml-1 text-emerald-300" />}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </fieldset>

      {!settings.available && (
        <p className="flex items-start gap-2 rounded-xl border border-amber-300/20 bg-amber-300/[0.04] px-3.5 py-3 text-small leading-5 text-amber-100/80">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-300" />
          <span>
            The permission system is switched off on this server, so there is
            nothing for the model to be permitted to do yet.
          </span>
        </p>
      )}

      {/* Advanced: per-tool overrides (collapsible, empty-state friendly) */}
      {settings.tools && settings.tools.length > 0 && (
        <div className="rounded-xl border border-white/[0.07]">
          <button
            type="button"
            className="flex w-full items-center gap-2.5 rounded-t-xl border-b border-white/[0.07] bg-white/[0.02] px-3.5 py-3 text-small font-medium text-zinc-300 transition hover:bg-white/[0.03]"
            onClick={() => setOverridesOpen((v) => !v)}
            aria-expanded={overridesOpen}
          >
            {overridesOpen ? <ChevronDown size={14} className="shrink-0 text-zinc-500" /> : <ChevronRight size={14} className="shrink-0 text-zinc-500" />}
            Advanced: per-tool overrides
            <span className="ml-auto rounded-full bg-white/[0.06] px-1.5 py-0.5 text-caption text-zinc-500">{settings.tools.length}</span>
          </button>
          {overridesOpen && (
            <div className="border-x border-b border-white/[0.07] px-3.5 py-3">
              {settings.tools.length === 0 ? (
                <p className="text-small text-zinc-500">Nothing here yet.</p>
              ) : (
                <ul className="space-y-1.5">
                  {settings.tools.map((tool) => {
                    const inherited = tool.category ? settings.categories?.[tool.category]?.label ?? tool.category : null
                    return (
                      <li key={tool.name} className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                        <span className="min-w-0 flex-1">
                          <span className="text-small text-zinc-200">{tool.name}</span>
                          <span className="ml-2 rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-micro text-zinc-500">
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
                            className={`shrink-0 rounded-lg border px-2.5 py-1 text-caption transition ${
                              tool.overrideEnabled
                                ? 'border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-200'
                                : 'border-white/[0.08] bg-white/[0.02] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300'
                            } ${busy ? 'cursor-not-allowed opacity-60' : ''}`}
                          >
                            {tool.overrideEnabled ? 'Override on' : 'Inherit'}
                          </button>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}             </div>
          )}
        </div>
      )}

      <p className="text-caption leading-5 text-zinc-600">
        Whatever you pick, actions that escalate — running a privileged command
        or deleting something you cannot get back — keep stopping for you.
        Permissions reduce interruptions; they never make the irreversible safe.
      </p>
    </div>
  )
}