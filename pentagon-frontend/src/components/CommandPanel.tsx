import { useState } from 'react'
import { Check, ChevronDown, CircleDashed, Terminal, X } from 'lucide-react'
import type { CommandRun, PendingCommand } from '../types'

/**
 * The approval prompt.
 *
 * This is the only thing standing between the model and a command, so it shows
 * the command itself rather than a summary of it, keeps it selectable so it can
 * be read closely or copied out, and says what happens on silence. The default
 * state is "not run": a timer expiring is a denial, and the wording says so.
 */
export function CommandApproval({
  pending,
  timeoutSeconds,
  busy,
  onDecide,
}: {
  pending: PendingCommand
  timeoutSeconds: number
  busy: boolean
  onDecide: (approved: boolean) => void
}) {
  const minutes = Math.max(1, Math.round(timeoutSeconds / 60))
  return (
    <section
      aria-label="Command approval"
      className="panel-enter my-3 overflow-hidden rounded-xl border border-amber-300/20 bg-amber-300/[0.04]"
    >
      <header className="flex items-center gap-2 border-b border-amber-300/10 px-3.5 py-2.5">
        <Terminal size={13} className="shrink-0 text-amber-300" />
        <span className="text-small font-medium text-amber-100">Pentagon wants to run a command</span>
      </header>
      <div className="px-3.5 py-3">
        {pending.reason && (
          <p className="mb-2.5 text-small leading-5 text-zinc-400">{pending.reason}</p>
        )}
        {/* Resolved on the server before the question was asked, so this names
            the actual window rather than repeating the model's wording. */}
        {pending.detail && (
          <p className="mb-2.5 rounded-lg border border-amber-300/10 bg-amber-300/[0.03] px-3 py-2 text-small leading-5 text-amber-100/90">
            <span className="text-zinc-500">This will affect: </span>
            {pending.detail}
          </p>
        )}
        {/* Not user-select:hidden -- the whole point is that this can be read
            and copied before it runs. */}
        <pre className="select-text overflow-x-auto rounded-lg border border-white/[0.08] bg-black/40 px-3 py-2.5 font-mono text-small leading-6 text-zinc-100">
          {pending.command}
        </pre>
        <p className="mt-2.5 text-micro leading-5 text-zinc-500">
          This is not read-only, so it is waiting for you. It runs with your own user account
          and never asks for more authority than you have. If you say nothing for {minutes}{' '}
          minute{minutes === 1 ? '' : 's'}, it will not run.
        </p>
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide(true)}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-amber-300 px-3 text-small font-semibold text-[#000000] transition hover:bg-amber-200 disabled:opacity-40"
          >
            <Check size={12} />
            Run it
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide(false)}
            className="flex h-8 items-center gap-1.5 rounded-lg border border-white/[0.1] px-3 text-small text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-40"
          >
            <X size={12} />
            Don&apos;t run
          </button>
          {busy && <span className="text-micro text-zinc-600">Sending your decision…</span>}
        </div>
      </div>
    </section>
  )
}

/**
 * What the commands did, once the turn is over.
 *
 * Read-only commands that ran unattended are shown too, not just the approved
 * ones: an allowlist nobody can inspect is not much of a safeguard.
 */
export function CommandLog({ runs }: { runs: CommandRun[] }) {
  const [open, setOpen] = useState(false)
  if (!runs.length) return null
  const failures = runs.filter((run) => !run.ok).length
  return (
    <section className="panel-enter my-3 overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.018]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left transition hover:bg-white/[0.03]"
      >
        <Terminal size={12} className="shrink-0 text-zinc-500" />
        <span className="text-small font-medium text-zinc-300">
          {runs.length} command{runs.length === 1 ? '' : 's'} run
        </span>
        {failures > 0 && (
          <span className="rounded-full bg-rose-400/10 px-1.5 text-[10px] tabular-nums text-rose-300">
            {failures} failed
          </span>
        )}
        <ChevronDown
          size={13}
          className={`ml-auto shrink-0 text-zinc-600 transition-transform duration-200 ${
            open ? 'rotate-180' : ''
          }`}
        />
      </button>
      {open && (
        <ul className="space-y-1.5 border-t border-white/[0.06] px-3.5 py-2.5">
          {runs.map((run, index) => (
            <li key={`${run.command}-${index}`}>
              <div className="flex items-baseline gap-2">
                {run.ok ? (
                  <Check size={11} className="mt-1 shrink-0 text-emerald-400" />
                ) : run.exit_code === null ? (
                  <CircleDashed size={11} className="mt-1 shrink-0 text-zinc-500" />
                ) : (
                  <X size={11} className="mt-1 shrink-0 text-rose-400" />
                )}
                <code className="min-w-0 flex-1 break-all font-mono text-micro leading-5 text-zinc-300">
                  {run.command}
                </code>
              </div>
              <p className="ml-[19px] mt-0.5 text-[10px] leading-4 text-zinc-600">
                {run.exit_code === null
                  ? 'Not run'
                  : `Exit ${run.exit_code}`}
                {' · '}
                {run.auto_approved ? 'read-only, ran automatically' : 'approved by you'}
                {run.timed_out && ' · timed out'}
                {' · '}
                {formatDuration(run.duration_ms)}
              </p>
              {(run.stdout || run.stderr) && (
                <pre className="ml-[19px] mt-1 max-h-40 select-text overflow-auto rounded-md border border-white/[0.06] bg-black/30 px-2 py-1.5 font-mono text-[10px] leading-4 text-zinc-500">
                  {(run.stdout || run.stderr).slice(0, 2000)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function formatDuration(ms: number) {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`
}