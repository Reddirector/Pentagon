import { useMemo, useState, useSyncExternalStore } from 'react'
import { Check, MessageSquarePlus, Pencil, Search, Settings2, Trash2, X } from 'lucide-react'
import { LogomarkBadge } from './Logomark'
import { getPreferences, subscribePreferences } from '../lib/preferences'
import type { Conversation } from '../types'

type Group = { title: string; conversations: Conversation[] }

function recencyGroups(conversations: Conversation[]): Group[] {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const groups = new Map<string, Conversation[]>([
    ['Today', []], ['Yesterday', []], ['Previous 7 Days', []], ['Earlier', []],
  ])
  for (const conversation of conversations) {
    const date = new Date(conversation.updated_at)
    date.setHours(0, 0, 0, 0)
    const day = Math.floor((today.getTime() - date.getTime()) / 86_400_000)
    const group = day <= 0 ? 'Today' : day === 1 ? 'Yesterday' : day <= 7 ? 'Previous 7 Days' : 'Earlier'
    groups.get(group)?.push(conversation)
  }
  return [...groups].map(([title, items]) => ({ title, conversations: items })).filter((group) => group.conversations.length > 0)
}

export function Sidebar({
  conversations,
  activeId,
  query,
  onQueryChange,
  onNewThread,
  onSelect,
  onRename,
  onDelete,
  onOpenPalette,
  onOpenSettings,
}: {
  conversations: Conversation[]
  activeId: string | null
  query: string
  onQueryChange: (value: string) => void
  onNewThread: () => void
  onSelect: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onOpenPalette?: () => void
  onOpenSettings?: () => void
}) {
  const groups = useMemo(() => recencyGroups(conversations.filter((item) => item.title.toLowerCase().includes(query.trim().toLowerCase()))), [conversations, query])
  const workspaceName = useSyncExternalStore(subscribePreferences, getPreferences).workspaceName
  // Inline rename state. Kept as an id rather than a map so that only the row
  // being edited re-renders its input state.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')

  function beginRename(id: string, title: string) {
    setEditingId(id)
    setDraftTitle(title || 'New thread')
  }

  function commitRename(id: string, originalTitle: string) {
    const next = draftTitle.trim()
    setEditingId(null)
    if (next && next !== originalTitle) onRename(id, next)
  }
  return <aside className="flex h-full w-[270px] shrink-0 flex-col border-r border-white/[0.07] bg-[var(--surface-sidebar)] px-4 py-5 backdrop-blur-2xl backdrop-saturate-150 max-lg:w-[230px] max-md:hidden">
    <div className="mb-8 flex items-center gap-3 px-2">
      <LogomarkBadge size={32} label="Pentagon" />
      <div><div className="text-[12px] font-semibold tracking-[.2em] text-zinc-100">PENTAGON</div><div className="mt-0.5 truncate text-[9px] uppercase tracking-[.18em] text-zinc-600">{workspaceName}</div></div>
    </div>

    <div className="mb-5 flex items-center gap-1.5">
      <button onClick={onNewThread} className="flex h-10 flex-1 items-center gap-2.5 rounded-xl border border-white/[0.09] bg-white/[0.035] px-3 text-left text-[12px] font-medium text-zinc-200 transition-[background-color,border-color,color,transform] duration-200 ease-out hover:-translate-y-px hover:border-emerald-300/30 hover:bg-emerald-300/[0.07] hover:text-white active:translate-y-0 active:scale-[.99]">
        <MessageSquarePlus size={15} className="text-emerald-300" />New Thread
      </button>
      <button type="button" onClick={onOpenPalette} className="grid h-10 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] text-[9px] text-zinc-600 transition hover:border-emerald-300/25 hover:text-zinc-300" title="Open command palette" aria-label="Open command palette">⌘K</button>
    </div>

    <div className="relative mb-6">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
      <input aria-label="Search conversations" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search threads" className="h-9 w-full rounded-lg border border-white/[0.06] bg-white/[0.025] pl-9 pr-3 text-[11px] text-zinc-200 outline-none transition placeholder:text-zinc-600 focus:border-emerald-300/30" />
    </div>

    <nav aria-label="Conversations" className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
      {groups.map((group) => <section key={group.title}>
        <h2 className="mb-2 px-2 text-[9px] font-medium uppercase tracking-[.18em] text-zinc-600">{group.title}</h2>
        <div className="space-y-0.5">
          {group.conversations.map((conversation) => (
            <div key={conversation.id} className="group relative">
              {editingId === conversation.id ? (
                <div className="flex items-center gap-1 rounded-lg bg-white/[0.06] px-2 py-1.5">
                  <input
                    autoFocus
                    value={draftTitle}
                    maxLength={120}
                    aria-label={`Rename ${conversation.title || 'thread'}`}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') commitRename(conversation.id, conversation.title || 'New thread')
                      if (event.key === 'Escape') setEditingId(null)
                    }}
                    className="min-w-0 flex-1 bg-transparent text-[11px] text-zinc-100 outline-none"
                  />
                  <button type="button" onClick={() => commitRename(conversation.id, conversation.title || 'New thread')} aria-label="Save name" className="shrink-0 rounded p-0.5 text-zinc-400 transition hover:text-zinc-100">
                    <Check size={12} />
                  </button>
                  <button type="button" onClick={() => setEditingId(null)} aria-label="Cancel rename" className="shrink-0 rounded p-0.5 text-zinc-400 transition hover:text-zinc-100">
                    <X size={12} />
                  </button>
                </div>
              ) : (
                <>
                  <button
                    onClick={() => onSelect(conversation.id)}
                    title={conversation.title || 'New thread'}
                    className={`block w-full truncate rounded-lg py-2.5 pl-2.5 pr-14 text-left text-[11px] transition-[background-color,color,box-shadow] duration-200 ease-out ${activeId === conversation.id ? 'bg-emerald-300/[0.09] font-medium text-emerald-100 shadow-[inset_2px_0_0_#ffffff]' : 'text-zinc-400 hover:bg-white/[0.045] hover:text-zinc-200'}`}
                  >
                    {conversation.title || 'New thread'}
                  </button>
                  {/* Actions stay hidden until hover or keyboard focus, so the
                      list reads as titles first. */}
                  <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                    <button
                      type="button"
                      onClick={() => beginRename(conversation.id, conversation.title)}
                      aria-label={`Rename ${conversation.title || 'thread'}`}
                      className="rounded p-1 text-zinc-500 transition hover:bg-white/[0.08] hover:text-zinc-200"
                    >
                      <Pencil size={11} />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm(`Delete "${conversation.title || 'New thread'}"?\n\nThis removes the thread and its messages from the server. It cannot be undone.`)) {
                          onDelete(conversation.id)
                        }
                      }}
                      aria-label={`Delete ${conversation.title || 'thread'}`}
                      className="rounded p-1 text-zinc-500 transition hover:bg-white/[0.08] hover:text-zinc-200"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      </section>)}
      {groups.length === 0 && <p className="px-2 text-[11px] leading-6 text-zinc-600">{query ? 'No matching threads.' : 'Your threads will appear here.'}</p>}
    </nav>

    <div className="mt-4 border-t border-white/[0.06] pt-3">
      <button type="button" onClick={onOpenSettings} className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition hover:bg-white/[0.045]">
        <Settings2 size={14} className="shrink-0 text-zinc-500" />
        <span className="text-[10px] text-zinc-400">Settings</span>
      </button>
    </div>
  </aside>
}
