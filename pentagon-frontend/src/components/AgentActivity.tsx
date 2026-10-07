import { useState, type FormEvent } from 'react'
import { Check, CircleAlert, FileText, HelpCircle, ListChecks, LoaderCircle, Wrench } from 'lucide-react'
import type { ChatMessage } from '../types'

/**
 * Everything an agent turn did, other than its prose: the plan it published,
 * the tools it ran, the questions it asked, the calls it wants approved, the
 * files it wrote, and the grounding verdict it finished with.
 *
 * Each block is plain HTML with a label a screen reader can announce; the
 * icons are decoration (`aria-hidden`) because the status word beside them
 * carries the meaning. Nothing here is a live region: a tool timeline that
 * announced every row would drown the very users it is for. The one polite
 * announcement is the open question or approval, which is genuinely new.
 */

const PLAN_LABEL: Record<string, string> = {
  done: 'done',
  in_progress: 'in progress',
  pending: 'pending',
  blocked: 'blocked',
}

function planIcon(status?: string) {
  if (status === 'done') return <Check size={11} aria-hidden="true" />
  if (status === 'blocked') return <CircleAlert size={11} aria-hidden="true" />
  if (status === 'in_progress') return <LoaderCircle size={11} className="animate-spin" aria-hidden="true" />
  return <span className="inline-block size-2 rounded-full border border-zinc-600" aria-hidden="true" />
}

function stepLabel(status?: string) {
  if (status === 'ok') return 'done'
  if (status === 'error') return 'failed'
  return 'running'
}

export function AgentActivity({
  message,
  busy,
  onApprove,
  onDeny,
  onAnswer,
}: {
  message: ChatMessage
  busy: boolean
  onApprove: (turnId: string, callIds: string[]) => void
  onDeny: (turnId: string) => void
  onAnswer: (turnId: string, text: string) => void
}) {
  const [draftAnswer, setDraftAnswer] = useState('')
  const steps = message.agentSteps ?? []
  const plan = message.agentPlan ?? []
  const artifacts = message.agentArtifacts ?? []
  const question = message.agentQuestion
  const approval = message.pendingToolApproval
  const notes = message.statusNotes ?? []
  const verification = message.verification
  const turnId = message.turnId

  if (!steps.length && !plan.length && !artifacts.length && !question && !approval && !notes.length && !verification) {
    return null
  }

  function submitAnswer(event: FormEvent) {
    event.preventDefault()
    const text = draftAnswer.trim()
    if (!text || !turnId || busy) return
    onAnswer(turnId, text)
    setDraftAnswer('')
  }

  return (
    <section aria-label="Agent activity" className="mt-3 space-y-3">
      {plan.length > 0 && (
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2.5">
          <p className="mb-1.5 flex items-center gap-1.5 text-micro font-medium uppercase tracking-[.12em] text-zinc-500">
            <ListChecks size={11} aria-hidden="true" /> Plan
          </p>
          <ol className="space-y-1">
            {plan.map((step, index) => (
              <li key={`${step.text}-${index}`} className="flex items-start gap-2 text-caption leading-5 text-zinc-300">
                <span className="mt-1 grid size-3 shrink-0 place-items-center text-emerald-300">{planIcon(step.status)}</span>
                <span className={step.status === 'done' ? 'text-zinc-500 line-through decoration-zinc-700' : undefined}>
                  {step.text}
                  <span className="ml-1.5 text-zinc-600">({PLAN_LABEL[step.status ?? 'pending'] ?? step.status})</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {approval && turnId && (
        <div role="group" aria-label="Tool approval required" className="rounded-xl border border-amber-300/20 bg-amber-300/[0.05] px-3 py-2.5">
          <p className="mb-1 text-caption font-medium text-amber-100/90">
            Pentagon wants to run {approval.calls.length === 1 ? `“${approval.calls[0].tool}”` : `${approval.calls.length} tools`}:
          </p>
          <ul className="mb-2 space-y-0.5">
            {approval.calls.map((call) => (
              <li key={call.id} className="font-mono text-[11px] text-amber-100/70">
                {call.tool}{call.tier ? ` · ${call.tier}` : ''}
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => onApprove(turnId, approval.calls.map((call) => call.id))}
              className="rounded-lg bg-amber-200/90 px-3 py-1.5 text-caption font-semibold text-black transition hover:bg-amber-100 disabled:opacity-50"
            >
              {busy ? 'Sending…' : 'Allow'}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDeny(turnId)}
              className="rounded-lg border border-white/[0.12] px-3 py-1.5 text-caption text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-50"
            >
              Deny
            </button>
          </div>
        </div>
      )}

      {question && !question.answered && turnId && (
        <div role="group" aria-label="Question from Pentagon" className="rounded-xl border border-sky-300/20 bg-sky-300/[0.05] px-3 py-2.5" aria-live="polite">
          <p className="mb-2 flex items-start gap-1.5 text-caption leading-5 text-sky-100/90">
            <HelpCircle size={12} className="mt-1 shrink-0" aria-hidden="true" />
            {question.question}
          </p>
          {question.options && question.options.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {question.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  disabled={busy}
                  onClick={() => onAnswer(turnId, option)}
                  className="rounded-lg border border-sky-300/25 bg-sky-300/[0.08] px-2.5 py-1.5 text-caption text-sky-100 transition hover:bg-sky-300/[0.16] disabled:opacity-50"
                >
                  {option}
                </button>
              ))}
            </div>
          ) : (
            <form onSubmit={submitAnswer} className="flex items-center gap-2">
              <label htmlFor={`answer-${message.id}`} className="sr-only">Your answer</label>
              <input
                id={`answer-${message.id}`}
                value={draftAnswer}
                onChange={(event) => setDraftAnswer(event.target.value)}
                disabled={busy}
                placeholder="Your answer…"
                className="h-8 min-w-0 flex-1 rounded-lg border border-white/[0.1] bg-black px-2.5 text-caption text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-sky-300/40"
              />
              <button
                type="submit"
                disabled={busy || !draftAnswer.trim()}
                className="rounded-lg bg-sky-300/90 px-3 py-1.5 text-caption font-semibold text-black transition hover:bg-sky-200 disabled:opacity-50"
              >
                Answer
              </button>
            </form>
          )}
        </div>
      )}

      {steps.length > 0 && (
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2.5">
          <p className="mb-1.5 flex items-center gap-1.5 text-micro font-medium uppercase tracking-[.12em] text-zinc-500">
            <Wrench size={11} aria-hidden="true" /> Tools
          </p>
          <ol className="space-y-1">
            {steps.map((step) => (
              <li key={step.id} className="flex items-baseline gap-2 text-caption leading-5">
                <span
                  className={
                    step.status === 'error'
                      ? 'shrink-0 rounded border border-rose-300/25 px-1 text-[10px] uppercase tracking-wide text-rose-200'
                      : step.status === 'ok'
                        ? 'shrink-0 rounded border border-emerald-300/25 px-1 text-[10px] uppercase tracking-wide text-emerald-200'
                        : 'shrink-0 rounded border border-white/[0.14] px-1 text-[10px] uppercase tracking-wide text-zinc-400'
                  }
                >
                  {stepLabel(step.status)}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-zinc-300" title={step.summary || step.tool}>
                  {step.tool}
                  {step.summary ? <span className="text-zinc-500"> — {step.summary}</span> : null}
                </span>
                {typeof step.elapsed_ms === 'number' && (
                  <span className="shrink-0 text-[10px] text-zinc-600">{Math.round(step.elapsed_ms)}ms</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {artifacts.length > 0 && (
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2.5">
          <p className="mb-1.5 text-micro font-medium uppercase tracking-[.12em] text-zinc-500">Artifacts</p>
          <ul className="flex flex-wrap gap-1.5">
            {artifacts.map((artifact) => (
              <li
                key={artifact.id}
                title={artifact.path}
                className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-emerald-300/12 bg-emerald-300/[0.05] px-2 py-1 text-caption text-emerald-100/85"
              >
                <FileText size={11} aria-hidden="true" />
                <span className="max-w-[200px] truncate">{artifact.name}</span>
                {typeof artifact.bytes === 'number' && (
                  <span className="text-[10px] text-emerald-100/50">{artifact.bytes}B</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {notes.length > 0 && (
        <ul className="space-y-0.5">
          {notes.map((note, index) => (
            <li key={`${index}-${note.slice(0, 24)}`} className="text-caption italic text-zinc-500">{note}</li>
          ))}
        </ul>
      )}

      {verification && (
        <p
          title={(verification.problems ?? []).join(' · ')}
          className={
            verification.ok
              ? 'inline-flex items-center gap-1.5 rounded-full border border-emerald-300/15 bg-emerald-300/[0.06] px-2.5 py-1 text-[11px] text-emerald-200/90'
              : 'inline-flex items-center gap-1.5 rounded-full border border-amber-300/15 bg-amber-300/[0.06] px-2.5 py-1 text-[11px] text-amber-100/90'
          }
        >
          {verification.ok ? <Check size={11} aria-hidden="true" /> : <CircleAlert size={11} aria-hidden="true" />}
          {verification.ok
            ? `Sources checked · ${verification.citations?.length ?? 0} cited from ${verification.sources ?? 0}`
            : 'Grounding check found problems with this answer'}
        </p>
      )}
    </section>
  )
}
