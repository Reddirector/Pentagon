/**
 * Pieces shared by the settings section components. Extracted verbatim from
 * SettingsDialog.tsx during the decomposition; the dialog re-exports some of
 * them so its own thin container keeps rendering exactly as before.
 */
import { useState } from 'react'
import { Check, Pencil, Sun, Trash2, X } from 'lucide-react'
import type { Conversation } from '../../types'

export const inputClass =
  'h-9 w-full rounded-lg border border-white/[0.09] bg-white/[0.03] px-3 text-body text-zinc-100 outline-none transition placeholder:text-zinc-700 focus:border-white/30'

// Kept separate from inputClass on purpose: adding bg-black/text-white on top of
// the input utilities would lose to them in the generated stylesheet, where
// source order decides, not the order written in the attribute.
export const selectClass =
  'h-9 w-full cursor-pointer rounded-lg border border-white/[0.12] bg-black px-3 text-body text-white outline-none transition focus:border-white/30'

export function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-white/[0.06] px-4 py-5 sm:px-6 last:border-b-0">
      <h3 className="text-micro font-medium uppercase tracking-[.16em] text-zinc-500">{title}</h3>
      {hint && <p className="mt-1.5 text-small leading-5 text-zinc-600">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

export function Choice({
  selected,
  onSelect,
  label,
  note,
  swatch,
  icon: Icon,
}: {
  selected: boolean
  onSelect: () => void
  label: string
  note: string
  swatch?: string
  icon?: typeof Sun
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={`flex w-full items-start gap-3 rounded-xl border px-3.5 py-3 text-left transition ${
        selected ? 'border-white/25 bg-white/[0.06]' : 'border-white/[0.07] bg-white/[0.02] hover:border-white/15'
      }`}
    >
      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
        {swatch ? (
          <span className="block size-4 rounded-full border border-white/25" style={{ background: swatch }} />
        ) : Icon ? (
          <Icon size={15} className={selected ? 'text-zinc-100' : 'text-zinc-500'} />
        ) : null}
      </span>
      <span className="min-w-0">
        <span className="block text-body font-medium text-zinc-100">{label}</span>
        <span className="mt-0.5 block text-micro-sm leading-[1.55] text-zinc-600">{note}</span>
      </span>
      {selected && <Check size={14} className="ml-auto mt-0.5 shrink-0 text-zinc-100" />}
    </button>
  )
}

export function ThreadRow({
  thread,
  onRename,
  onDelete,
}: {
  thread: Conversation
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(thread.title || 'New thread')
  const label = thread.title || 'New thread'

  function save() {
    const next = draft.trim()
    setEditing(false)
    if (next && next !== thread.title) onRename(thread.id, next)
  }

  function cancel() {
    setDraft(label)
    setEditing(false)
  }

  return (
    <li className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
      {editing ? (
        <>
          <input
            autoFocus
            value={draft}
            maxLength={120}
            aria-label={`Rename ${label}`}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') save()
              if (event.key === 'Escape') cancel()
            }}
            className="min-w-0 flex-1 bg-transparent text-small-lg text-zinc-100 outline-none"
          />
          <button type="button" onClick={save} aria-label="Save name" className="shrink-0 rounded p-1 text-zinc-400 transition hover:text-zinc-100">
            <Check size={12} />
          </button>
          <button type="button" onClick={cancel} aria-label="Cancel rename" className="shrink-0 rounded p-1 text-zinc-400 transition hover:text-zinc-100">
            <X size={12} />
          </button>
        </>
      ) : (
        <>
          <span className="min-w-0 flex-1 truncate text-small-lg text-zinc-300">{label}</span>
          <button
            type="button"
            onClick={() => setEditing(true)}
            aria-label={`Rename ${label}`}
            className="shrink-0 rounded p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <Pencil size={12} />
          </button>
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`Delete "${label}"?\n\nThis removes the thread and its messages from the server. It cannot be undone.`)) {
                onDelete(thread.id)
              }
            }}
            aria-label={`Delete ${label}`}
            className="shrink-0 rounded p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <Trash2 size={12} />
          </button>
        </>
      )}
    </li>
  )
}
