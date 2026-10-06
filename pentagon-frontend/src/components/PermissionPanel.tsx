import { Check, Lock, Shield, ShieldAlert, Sparkles } from 'lucide-react'
import type { CommandSettings, PermissionLevel } from '../types'

/**
 * The permission granting panel.
 *
 * Shown in two places -- as a tab in the chat area and as a tab in Settings --
 * so the wording a user reads about a level is identical in both, and there is
 * only one place in this codebase that knows how to ask the question.
 *
 * Three rungs, described by the server rather than hard-coded here. That is
 * deliberate: the panel is how a user finds out what "Trusted" will let the
 * model do, so if the server ever changes what a level means, this must not be
 * the copy that still disagrees with it.
 */

const LEVEL_ICONS = [Lock, Shield, Sparkles] as const

function iconFor(level: number) {
  return LEVEL_ICONS[Math.min(Math.max(level, 1), 3) - 1]
}

export function PermissionPanel({
  settings,
  onChange,
  busy = false,
}: {
  settings: CommandSettings
  onChange: (level: number) => void | Promise<void>
  busy?: boolean
}) {
  const levels = settings.permission_levels.length
    ? settings.permission_levels
    : FALLBACK_LEVELS
  const current = settings.permission_level

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-body font-medium text-zinc-100">Permissions</h2>
        <p className="mt-1 text-small leading-5 text-zinc-500">
          How much Pentagon may do without stopping to ask you. This applies to
          shell commands and desktop control alike.
        </p>
      </div>

      <fieldset className="space-y-2" disabled={busy || !settings.available}>
        <legend className="sr-only">Permission level</legend>
        {levels.map((level) => {
          const Icon = iconFor(level.level)
          const selected = level.level === current
          return (
            <label
              key={level.level}
              className={`panel-enter flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 transition ${
                selected
                  ? 'border-emerald-300/30 bg-emerald-300/[0.06]'
                  : 'border-white/[0.09] bg-white/[0.015] hover:border-white/[0.16] hover:bg-white/[0.035]'
              } ${busy || !settings.available ? 'cursor-not-allowed opacity-60' : ''}`}
            >
              {/* A radio, not a button: arrow keys move between levels and the
                  group reads as one question with one answer. */}
              <input
                type="radio"
                name="permission-level"
                className="sr-only"
                checked={selected}
                disabled={busy || !settings.available}
                onChange={() => void onChange(level.level)}
              />
              <span
                aria-hidden="true"
                className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg border ${
                  selected
                    ? 'border-emerald-300/40 bg-emerald-300/10 text-emerald-200'
                    : 'border-white/[0.12] text-zinc-500'
                }`}
              >
                <Icon size={14} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-small font-medium text-zinc-100">
                    {level.name}
                  </span>
                  {selected && (
                    <span className="inline-flex items-center gap-1 rounded-md border border-emerald-300/25 bg-emerald-300/10 px-1.5 py-0.5 text-caption-xs text-emerald-200">
                      <Check size={10} />
                      Current
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block text-caption text-zinc-400">
                  {level.summary}
                </span>
                <span className="mt-1.5 block text-caption leading-5 text-zinc-500">
                  {level.detail}
                </span>
              </span>
            </label>
          )
        })}
      </fieldset>

      {!settings.available && (
        <p className="flex items-start gap-2 rounded-xl border border-amber-300/20 bg-amber-300/[0.04] px-3.5 py-3 text-small leading-5 text-amber-100/80">
          <ShieldAlert size={14} className="mt-0.5 shrink-0 text-amber-300" />
          <span>
            Commands are switched off on this server, so there is nothing for
            the model to be permitted to do yet.
          </span>
        </p>
      )}

      {settings.available && !settings.enabled && (
        <p className="rounded-xl border border-white/[0.09] bg-white/[0.02] px-3.5 py-3 text-small leading-5 text-zinc-400">
          Your chosen level is saved now and takes effect the moment you turn
          commands on.
        </p>
      )}

      <p className="text-caption leading-5 text-zinc-600">
        Raising a level only removes interruptions. Commands that escalate --
        <code className="mx-1 text-zinc-500">sudo</code>and friends -- are
        refused at every level, with or without your approval.
      </p>
    </div>
  )
}

/**
 * Shown only if the server sent no ladder, which would mean the client and the
 * server disagree about the API. It is deliberately the same three rungs in the
 * same order, so a mismatched build degrades to something honest rather than to
 * a blank panel.
 */
const FALLBACK_LEVELS: PermissionLevel[] = [
  { level: 1, name: 'Restricted', summary: 'Ask me before anything runs', detail: '' },
  { level: 2, name: 'Balanced', summary: 'Read freely, ask before changing', detail: '' },
  { level: 3, name: 'Trusted', summary: 'Run freely, ask before destroying', detail: '' },
]