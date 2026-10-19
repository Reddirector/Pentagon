import { useState, type FormEvent } from 'react'
import {
  Check,
  ChevronDown,
  CircleAlert,
  FileCode,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  Image as ImageIcon,
  ListChecks,
  LoaderCircle,
  Search,
  Wrench,
} from 'lucide-react'
import type { ChatMessage } from '../types'

const TOOL_CONFIG: Record<string, { label: string; icon: typeof Wrench }> = {
  web_search: { label: 'Web Search', icon: Search },
  search_web: { label: 'Web Search', icon: Search },
  deep_research: { label: 'Deep Research', icon: Search },
  fetch_url: { label: 'Fetch Page', icon: Search },
  browse_page: { label: 'Browse Page', icon: Search },
  document_generation: { label: 'Generate Document', icon: FileText },
  image_generation: { label: 'Generate Image', icon: ImageIcon },
  calculator: { label: 'Calculator', icon: Wrench },
  python_exec: { label: 'Code Execution', icon: FileCode },
  search_documents: { label: 'Document Search', icon: FileSpreadsheet },
  read_document: { label: 'Read Document', icon: FileText },
  run_shell_command: { label: 'Shell Command', icon: Wrench },
  run_desktop_action: { label: 'Desktop Action', icon: Wrench },
  run_location_tool: { label: 'Location Check', icon: Wrench },
  create_artifact: { label: 'Create Artifact', icon: FileText },
  update_plan: { label: 'Plan Update', icon: ListChecks },
  ask_user: { label: 'Question', icon: HelpCircle },
}

function parseToolSummary(_tool: string, rawSummary?: string): string {
  if (!rawSummary) return ''
  const trimmed = rawSummary.trim()

  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const data = JSON.parse(trimmed)
      if (typeof data.query === 'string') return `"${data.query}"`
      if (typeof data.title === 'string') return `"${data.title}"`
      if (typeof data.filename === 'string') return `"${data.filename}"`
      if (typeof data.expression === 'string') return `${data.expression}`
      if (typeof data.url === 'string') return `${data.url}`
      if (typeof data.question === 'string') return `"${data.question}"`
    } catch {
      // JSON parse error, fallback to regex
    }
  }

  const qMatch = trimmed.match(/"query"\s*:\s*"([^"]+)"/)
  if (qMatch) return `"${qMatch[1]}"`
  const tMatch = trimmed.match(/"title"\s*:\s*"([^"]+)"/)
  if (tMatch) return `"${tMatch[1]}"`
  const fMatch = trimmed.match(/"filename"\s*:\s*"([^"]+)"/)
  if (fMatch) return `"${fMatch[1]}"`

  if (trimmed.startsWith('{') || trimmed.includes('{"')) {
    return ''
  }

  return trimmed.length > 70 ? `${trimmed.slice(0, 70)}…` : trimmed
}

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
  const [toolsOpen, setToolsOpen] = useState(false)
  const steps = message.agentSteps ?? []
  const plan = message.agentPlan ?? []
  const artifacts = message.agentArtifacts ?? []
  const question = message.agentQuestion
  const approval = message.pendingToolApproval
  const rawNotes = message.statusNotes ?? []
  const verification = message.verification
  const turnId = message.turnId

  const isFailed = rawNotes.some((n) => /failed/i.test(n) || /error/i.test(n)) || (typeof message.content === 'string' && message.content.startsWith('I could not complete that request'))
  const isConnected = !isFailed && rawNotes.some((n) => /^connected/i.test(n.trim()))
  const showConnection = isConnected || isFailed
  const modelName = message.model_used

  if (!steps.length && !plan.length && !artifacts.length && !question && !approval && !showConnection && !verification) {
    return null
  }

  const hasRunning = steps.some((s) => s.status === 'running')
  const okCount = steps.filter((s) => s.status === 'ok').length
  const errCount = steps.filter((s) => s.status === 'error').length
  const totalMs = steps.reduce((acc, s) => acc + (s.elapsed_ms || 0), 0)

  // Unique tools set
  const uniqueTools = Array.from(new Set(steps.map((s) => TOOL_CONFIG[s.tool]?.label || s.tool.replace(/_/g, ' '))))
  const toolSummaryText = uniqueTools.slice(0, 3).join(', ') + (uniqueTools.length > 3 ? ` +${uniqueTools.length - 3}` : '')

  function submitAnswer(event: FormEvent) {
    event.preventDefault()
    const text = draftAnswer.trim()
    if (!text || !turnId || busy) return
    onAnswer(turnId, text)
    setDraftAnswer('')
  }

  return (
    <section aria-label="Agent activity" className="my-2.5 space-y-2.5">
      {showConnection && (
        <div className="flex flex-wrap items-center gap-1.5 text-caption text-zinc-400">
          <span className="inline-flex items-center gap-1.5 font-medium">
            <span
              className={`size-1.5 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-rose-400'}`}
              aria-hidden="true"
            />
            <span className={isConnected ? 'text-emerald-400' : 'text-rose-400'}>
              {isConnected ? 'Connected' : 'Failed to connect'}
            </span>
          </span>
          {modelName && (
            <>
              <span className="text-zinc-600" aria-hidden="true">·</span>
              <span className="font-mono text-[11px] text-zinc-400">{modelName}</span>
            </>
          )}
        </div>
      )}

      {approval && turnId && (
        <div role="group" aria-label="Tool approval required" className="rounded-xl border border-amber-300/20 bg-amber-300/[0.05] p-3 shadow-sm">
          <p className="mb-1 text-caption font-medium text-amber-100/90">
            Pentagon requests approval to execute {approval.calls.length === 1 ? `“${approval.calls[0].tool}”` : `${approval.calls.length} actions`}:
          </p>
          <ul className="mb-2.5 space-y-1">
            {approval.calls.map((call) => (
              <li key={call.id} className="font-mono text-[11px] text-amber-100/75">
                • {call.tool}{call.tier ? ` · ${call.tier}` : ''}
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => onApprove(turnId, approval.calls.map((call) => call.id))}
              className="rounded-lg bg-amber-200/90 px-3.5 py-1.5 text-caption font-semibold text-black transition hover:bg-amber-100 disabled:opacity-50"
            >
              {busy ? 'Sending…' : 'Approve'}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDeny(turnId)}
              className="rounded-lg border border-white/[0.12] px-3.5 py-1.5 text-caption text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-50"
            >
              Decline
            </button>
          </div>
        </div>
      )}

      {question && !question.answered && turnId && (
        <div role="group" aria-label="Question from Pentagon" className="rounded-xl border border-sky-300/20 bg-sky-300/[0.05] p-3 shadow-sm" aria-live="polite">
          <p className="mb-2 flex items-start gap-1.5 text-caption leading-5 text-sky-100/90">
            <HelpCircle size={14} className="mt-0.5 shrink-0 text-sky-400" aria-hidden="true" />
            <span>{question.question}</span>
          </p>
          {question.options && question.options.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {question.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  disabled={busy}
                  onClick={() => onAnswer(turnId, option)}
                  className="rounded-lg border border-sky-300/25 bg-sky-300/[0.08] px-3 py-1.5 text-caption text-sky-100 transition hover:bg-sky-300/[0.18] disabled:opacity-50"
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
                placeholder="Type your response…"
                className="h-8 min-w-0 flex-1 rounded-lg border border-white/[0.1] bg-black/60 px-2.5 text-caption text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-sky-300/40"
              />
              <button
                type="submit"
                disabled={busy || !draftAnswer.trim()}
                className="rounded-lg bg-sky-300/90 px-3.5 py-1.5 text-caption font-semibold text-black transition hover:bg-sky-200 disabled:opacity-50"
              >
                Send
              </button>
            </form>
          )}
        </div>
      )}

      {plan.length > 0 && (
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
          <p className="mb-2 flex items-center gap-1.5 text-micro font-medium uppercase tracking-[.12em] text-zinc-500">
            <ListChecks size={12} className="text-emerald-400" aria-hidden="true" /> Execution Plan
          </p>
          <ol className="space-y-1.5">
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

      {steps.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.015]">
          <button
            type="button"
            onClick={() => setToolsOpen(!toolsOpen)}
            className="flex w-full items-center justify-between px-3.5 py-2 text-left transition hover:bg-white/[0.03]"
            aria-expanded={toolsOpen}
          >
            <div className="flex items-center gap-2 min-w-0">
              <Wrench size={12} className="text-zinc-400 shrink-0" aria-hidden="true" />
              <span className="truncate text-[11px] font-medium text-zinc-300">
                {hasRunning ? (
                  <span className="inline-flex items-center gap-1.5 text-sky-300">
                    <LoaderCircle size={11} className="animate-spin shrink-0" />
                    Working with tools ({steps.length} {steps.length === 1 ? 'action' : 'actions'})…
                  </span>
                ) : (
                  <span>
                    Executed {steps.length} {steps.length === 1 ? 'action' : 'actions'} ({okCount} ok{errCount > 0 ? `, ${errCount} failed` : ''} · {toolSummaryText})
                    {totalMs > 0 && <span className="text-zinc-500 font-normal"> · {(totalMs / 1000).toFixed(1)}s</span>}
                  </span>
                )}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-micro text-zinc-500 shrink-0">
              <span>{toolsOpen ? 'Hide' : 'Details'}</span>
              <ChevronDown size={13} className={`transition-transform duration-200 ${toolsOpen ? 'rotate-180' : ''}`} />
            </div>
          </button>

          {(toolsOpen || hasRunning) && (
            <div className="border-t border-white/[0.05] p-2.5 bg-black/20">
              <ol className="space-y-1.5 max-h-[320px] overflow-y-auto pr-1">
                {steps.map((step) => {
                  const Icon = TOOL_CONFIG[step.tool]?.icon || Wrench
                  const detail = parseToolSummary(step.tool, step.summary)
                  return (
                    <li
                      key={step.id}
                      className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.04] bg-white/[0.01] px-2.5 py-1.5 text-caption leading-5"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          className={
                            step.status === 'error'
                              ? 'shrink-0 rounded border border-rose-400/25 bg-rose-400/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-rose-300'
                              : step.status === 'ok'
                                ? 'shrink-0 rounded border border-emerald-400/25 bg-emerald-400/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-300'
                                : 'shrink-0 rounded border border-sky-400/25 bg-sky-400/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-sky-300'
                          }
                        >
                          {step.status === 'running' ? (
                            <span className="flex items-center gap-1">
                              <LoaderCircle size={8} className="animate-spin" />
                              run
                            </span>
                          ) : (
                            stepLabel(step.status)
                          )}
                        </span>
                        <Icon size={12} className="shrink-0 text-zinc-400" aria-hidden="true" />
                        <span className="shrink-0 font-medium text-zinc-200 text-[11px]">
                          {TOOL_CONFIG[step.tool]?.label ?? step.tool.replace(/_/g, ' ')}
                        </span>
                        {detail && (
                          <span className="truncate text-[11px] text-zinc-400" title={detail}>
                            {detail}
                          </span>
                        )}
                      </div>
                      {typeof step.elapsed_ms === 'number' && (
                        <span className="shrink-0 font-mono text-[10px] text-zinc-500">
                          {Math.round(step.elapsed_ms)}ms
                        </span>
                      )}
                    </li>
                  )
                })}
              </ol>
            </div>
          )}
        </div>
      )}

      {artifacts.length > 0 && (
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-2.5">
          <p className="mb-1.5 text-micro font-medium uppercase tracking-[.12em] text-zinc-500">Artifacts</p>
          <ul className="flex flex-wrap gap-1.5">
            {artifacts.map((artifact) => (
              <li
                key={artifact.id}
                title={artifact.path}
                className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-emerald-300/12 bg-emerald-300/[0.05] px-2.5 py-1 text-caption text-emerald-100/85"
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


      {verification && (
        <div className="pt-0.5">
          <span
            title={(verification.problems ?? []).join(' · ')}
            className={
              verification.ok
                ? 'inline-flex items-center gap-1.5 rounded-full border border-emerald-400/20 bg-emerald-400/[0.06] px-2.5 py-1 text-[11px] text-emerald-200/90'
                : 'inline-flex items-center gap-1.5 rounded-full border border-amber-400/20 bg-amber-400/[0.06] px-2.5 py-1 text-[11px] text-amber-200/90'
            }
          >
            {verification.ok ? <Check size={11} className="text-emerald-400" aria-hidden="true" /> : <CircleAlert size={11} className="text-amber-400" aria-hidden="true" />}
            {verification.ok
              ? `Grounding verified · ${verification.citations?.length ?? 0} cited from ${verification.sources ?? 0} sources`
              : 'Grounding check flagged discrepancies in sources'}
          </span>
        </div>
      )}
    </section>
  )
}

