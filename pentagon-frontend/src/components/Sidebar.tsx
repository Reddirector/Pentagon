import { useMemo } from 'react'
import { MessageSquarePlus, Search, Settings2 } from 'lucide-react'
import { LogomarkBadge } from './Logomark'
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
  userId,
  query,
  onQueryChange,
  onNewThread,
  onSelect,
  onOpenPalette,
  onOpenSettings,
}: {
  conversations: Conversation[]
  activeId: string | null
  userId: string
  query: string
  onQueryChange: (value: string) => void
  onNewThread: () => void
  onSelect: (id: string) => void
  onOpenPalette?: () => void
  onOpenSettings?: () => void
}) {
  const groups = useMemo(() => recencyGroups(conversations.filter((item) => item.title.toLowerCase().includes(query.trim().toLowerCase()))), [conversations, query])
  return <aside className="flex h-full w-[270px] shrink-0 flex-col border-r border-white/[0.07] bg-[#0d1016]/72 px-4 py-5 backdrop-blur-2xl backdrop-saturate-150 max-lg:w-[230px] max-md:hidden">
    <div className="mb-8 flex items-center gap-3 px-2">
      <LogomarkBadge size={32} label="Pentagon" />
      <div><div className="text-[12px] font-semibold tracking-[.2em] text-zinc-100">PENTAGON</div><div className="mt-0.5 text-[9px] uppercase tracking-[.18em] text-zinc-600">Personal workspace</div></div>
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
          {group.conversations.map((conversation) => <button key={conversation.id} onClick={() => onSelect(conversation.id)} title={conversation.title} className={`block w-full truncate rounded-lg px-2.5 py-2.5 text-left text-[11px] transition-[background-color,color,box-shadow] duration-200 ease-out ${activeId === conversation.id ? 'bg-emerald-300/[0.09] font-medium text-emerald-100 shadow-[inset_2px_0_0_#6ee7b7]' : 'text-zinc-400 hover:bg-white/[0.045] hover:text-zinc-200'}`}>
            {conversation.title || 'New thread'}
          </button>)}
        </div>
      </section>)}
      {groups.length === 0 && <p className="px-2 text-[11px] leading-6 text-zinc-600">{query ? 'No matching threads.' : 'Your threads will appear here.'}</p>}
    </nav>

    <div className="mt-4 border-t border-white/[0.06] pt-4">
      <div className="flex items-center gap-2.5 px-2">
        <div className="grid size-7 place-items-center rounded-full border border-white/10 bg-white/[0.045] font-mono text-[10px] text-zinc-300">{userId.slice(-1).toUpperCase()}</div>
        <div className="min-w-0"><div className="text-[10px] font-medium text-zinc-300">Local session</div><div className="truncate text-[9px] text-zinc-600">{userId}</div></div>
        <span className="ml-auto size-1.5 rounded-full bg-emerald-300 shadow-[0_0_8px_rgba(110,231,183,.7)]" title="Backend connected" />
      </div>
      <button type="button" onClick={onOpenSettings} className="mt-2 flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition hover:bg-white/[0.045]" title="Settings">
        <Settings2 size={14} className="shrink-0 text-zinc-500" />
        <span className="text-[10px] text-zinc-400">Settings</span>
        <span className="ml-auto text-[9px] text-zinc-700">ambient, shortcuts</span>
      </button>
    </div>
  </aside>
}
