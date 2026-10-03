import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import {
  Check,
  MessageSquare,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Search,
  Settings2,
  Trash2,
  X,
} from 'lucide-react'
import { LogomarkBadge } from './Logomark'
import {
  getPreferences,
  setSidebarCollapsed as persistSidebarCollapsed,
  setSidebarWidth as persistSidebarWidth,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_RAIL_WIDTH,
  subscribePreferences,
} from '../lib/preferences'
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
  open = false,
  onClose,
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
  /** Drawer state. Only meaningful below the md breakpoint, where the sidebar
      becomes an overlay instead of a column. */
  open?: boolean
  onClose?: () => void
}) {
  const groups = useMemo(() => recencyGroups(conversations.filter((item) => item.title.toLowerCase().includes(query.trim().toLowerCase()))), [conversations, query])
  const preferences = useSyncExternalStore(subscribePreferences, getPreferences)
  const workspaceName = preferences.workspaceName
  // Inline rename state. Kept as an id rather than a map so that only the row
  // being edited re-renders its input state.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')

  // --- Resizing ---------------------------------------------------------------
  // Width is only user-adjustable from md up; below that the sidebar is a
  // drawer whose width is dictated by the viewport, so the handle is hidden and
  // the stored width is not applied.
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(min-width: 768px)').matches,
  )
  const asideRef = useRef<HTMLElement>(null)
  const [draftWidth, setDraftWidth] = useState<number | null>(null)
  const [resizing, setResizing] = useState(false)
  const widthPreference = preferences.sidebarWidth

  // The rail is a desktop-only affordance. On a phone the sidebar is an overlay
  // drawer that is already as narrow as it can usefully be, so collapsing it
  // would only make it harder to read.
  const collapsed = isDesktop && preferences.sidebarCollapsed

  useEffect(() => {
    const query = window.matchMedia('(min-width: 768px)')
    const onChange = (event: MediaQueryListEvent) => setIsDesktop(event.matches)
    onChange({ matches: query.matches } as MediaQueryListEvent)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  // A collapsed rail has a fixed width, so the stored width is set aside rather
  // than overwritten — expanding again restores whatever the user had chosen.
  const appliedWidth = collapsed ? SIDEBAR_RAIL_WIDTH : (draftWidth ?? (widthPreference > 0 ? widthPreference : null))

  // Search lives in the input, which the rail has no room for. Asking for it
  // from the rail therefore expands the sidebar and focuses the field, which is
  // what the magnifier is understood to mean. The focus is deferred to a
  // callback ref rather than an effect, so it happens the moment the input
  // actually exists instead of costing an extra render.
  const focusSearchOnMount = useRef(false)
  const attachSearch = useCallback((node: HTMLInputElement | null) => {
    if (!node || !focusSearchOnMount.current) return
    focusSearchOnMount.current = false
    node.focus()
    node.select()
  }, [])

  function clamp(value: number) {
    return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(value)))
  }

  function beginResize(event: React.PointerEvent<HTMLDivElement>) {
    if (!isDesktop || event.button !== 0) return
    event.preventDefault()
    const startX = event.clientX
    const startWidth = asideRef.current?.getBoundingClientRect().width ?? SIDEBAR_DEFAULT_WIDTH
    setResizing(true)

    // The live width is mirrored in a ref so the commit on release never has to
    // happen inside a state updater, which React runs during render.
    const latest = { value: null as number | null }
    const onMove = (move: PointerEvent) => {
      latest.value = clamp(startWidth + (move.clientX - startX))
      setDraftWidth(latest.value)
    }
    const finish = () => {
      if (latest.value !== null) persistSidebarWidth(latest.value)
      setDraftWidth(null)
      setResizing(false)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
  }

  function nudgeWidth(delta: number) {
    // Deliberately not appliedWidth: while collapsed that is the 64px rail, and
    // nudging from there would clamp to the minimum and overwrite the width the
    // user actually chose. Keyboard resizing works on the stored width.
    const current = widthPreference > 0
      ? widthPreference
      : asideRef.current?.getBoundingClientRect().width ?? SIDEBAR_DEFAULT_WIDTH
    persistSidebarWidth(clamp(current + delta))
  }

  function resetWidth() {
    persistSidebarWidth(0)
    setDraftWidth(null)
  }

  // Stop stray text selection while the pointer is dragging the divider.
  useEffect(() => {
    if (!resizing) return
    const previous = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    return () => {
      document.body.style.userSelect = previous
    }
  }, [resizing])

  useEffect(() => {
    if (!open || !onClose) return
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  function beginRename(id: string, title: string) {
    setEditingId(id)
    setDraftTitle(title || 'New thread')
  }

  function commitRename(id: string, originalTitle: string) {
    const next = draftTitle.trim()
    setEditingId(null)
    if (next && next !== originalTitle) onRename(id, next)
  }

  return <aside
    ref={asideRef}
    aria-label="Threads"
    // Below md this is a fixed drawer that slides in over the conversation;
    // from md up it is a plain flex column and the transform is neutralised.
    // md:relative (not static) so the resize handle can anchor to this element.
    style={isDesktop && appliedWidth ? { width: `${appliedWidth}px` } : undefined}
    className={`fixed inset-y-0 left-0 z-40 flex h-full w-[min(86vw,300px)] shrink-0 flex-col border-r border-white/[0.07] bg-[var(--surface-sidebar)] py-5 shadow-[0_0_60px_rgba(0,0,0,.6)] backdrop-blur-2xl backdrop-saturate-150 transition-transform duration-200 ease-out md:relative md:z-auto md:w-[270px] md:translate-x-0 md:shadow-none lg:w-[230px] xl:w-[270px] ${collapsed ? 'px-3' : 'px-4'} ${open ? 'translate-x-0' : '-translate-x-full'}`}
  >
  {isDesktop && !collapsed ? (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuenow={Math.round(appliedWidth ?? SIDEBAR_DEFAULT_WIDTH)}
      aria-valuemin={SIDEBAR_MIN_WIDTH}
      aria-valuemax={SIDEBAR_MAX_WIDTH}
      tabIndex={0}
      onPointerDown={beginResize}
      onDoubleClick={resetWidth}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') nudgeWidth(-16)
        if (event.key === 'ArrowRight') nudgeWidth(16)
        if (event.key === 'Home') resetWidth()
      }}
      title="Drag to resize · double-click to reset"
      className="group absolute inset-y-0 -right-1 z-20 w-2 cursor-col-resize touch-none focus:outline-none"
    >
      <span
        className={`absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors duration-150 ${
          resizing ? 'bg-white/70' : 'bg-white/0 group-hover:bg-white/25 group-focus-visible:bg-white/50'
        }`}
      />
    </div>
  ) : null}
  {collapsed ? (
    <div className="mb-6 flex flex-col items-center gap-3">
      <LogomarkBadge size={30} label="Pentagon" />
      <button
        type="button"
        onClick={() => persistSidebarCollapsed(false)}
        aria-label="Expand sidebar"
        title="Expand sidebar (⌘B)"
        className="grid size-8 place-items-center rounded-lg text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-100"
      >
        <PanelLeftOpen size={15} />
      </button>
    </div>
  ) : (
    <>
    <div className="mb-8 flex items-center gap-3 px-2">
      <button
        type="button"
        onClick={onClose}
        aria-label="Close navigation"
        className="-ml-2 grid size-8 shrink-0 place-items-center rounded-lg text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-100 md:hidden"
      >
        <X size={16} />
      </button>
      <LogomarkBadge size={32} label="Pentagon" />
      <div className="min-w-0 flex-1"><div className="text-body font-semibold tracking-[.2em] text-zinc-100">PENTAGON</div><div className="mt-0.5 truncate text-caption uppercase tracking-[.18em] text-zinc-600">{workspaceName}</div></div>
      {isDesktop ? (
        <button
          type="button"
          onClick={() => persistSidebarCollapsed(true)}
          aria-label="Collapse sidebar"
          title="Collapse sidebar (⌘B)"
          className="grid size-8 shrink-0 place-items-center rounded-lg text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-100"
        >
          <PanelLeftClose size={15} />
        </button>
      ) : null}
    </div>
    </>
  )}

  {collapsed ? (
    <div className="mb-5 flex flex-col items-center gap-1.5">
      <button
        type="button"
        onClick={onNewThread}
        aria-label="New thread"
        title="New thread"
        className="grid size-9 place-items-center rounded-xl border border-white/[0.09] bg-white/[0.035] text-zinc-200 transition hover:border-emerald-300/30 hover:bg-emerald-300/[0.07] hover:text-white"
      >
        <MessageSquarePlus size={15} className="text-emerald-300" />
      </button>
      <button
        type="button"
        onClick={() => {
          focusSearchOnMount.current = true
          persistSidebarCollapsed(false)
        }}
        aria-label="Search threads"
        title="Search threads"
        className="grid size-9 place-items-center rounded-xl border border-white/[0.07] text-zinc-500 transition hover:border-emerald-300/25 hover:text-zinc-200"
      >
        <Search size={15} />
      </button>
    </div>
  ) : (
    <>
  <div className="mb-5 flex items-center gap-1.5">
    <button onClick={onNewThread} className="flex h-10 flex-1 items-center gap-2.5 rounded-xl border border-white/[0.09] bg-white/[0.035] px-3 text-left text-body font-medium text-zinc-200 transition-[background-color,border-color,color,transform] duration-200 ease-out hover:-translate-y-px hover:border-emerald-300/30 hover:bg-emerald-300/[0.07] hover:text-white active:translate-y-0 active:scale-[.99]">
      <MessageSquarePlus size={15} className="text-emerald-300" />New Thread
    </button>
    <button type="button" onClick={onOpenPalette} className="grid h-10 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] text-caption text-zinc-600 transition hover:border-emerald-300/25 hover:text-zinc-300" title="Open command palette" aria-label="Open command palette">⌘K</button>
  </div>

  <div className="relative mb-6">
    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
    <input ref={attachSearch} aria-label="Search conversations" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search threads" className="h-9 w-full rounded-lg border border-white/[0.06] bg-white/[0.025] pl-9 pr-3 text-small text-zinc-200 outline-none transition placeholder:text-zinc-600 focus:border-emerald-300/30" />
  </div>
    </>
  )}

  {collapsed ? (
    <nav aria-label="Conversations" className="min-h-0 flex-1 space-y-4 overflow-y-auto">
      {groups.map((group) => (
        <section key={group.title} className="space-y-1">
          <div className="mx-auto h-px w-5 bg-white/[0.09]" aria-hidden="true" />
          {group.conversations.map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => onSelect(conversation.id)}
              title={conversation.title || 'New thread'}
              aria-label={conversation.title || 'New thread'}
              aria-current={activeId === conversation.id}
              className={`mx-auto grid size-9 place-items-center rounded-lg transition-[background-color,color] duration-200 ease-out ${
                activeId === conversation.id
                  ? 'bg-emerald-300/[0.12] text-emerald-100'
                  : 'text-zinc-500 hover:bg-white/[0.045] hover:text-zinc-200'
              }`}
            >
              <MessageSquare size={15} />
            </button>
          ))}
        </section>
      ))}
      {groups.length === 0 && (
        <p className="px-1 text-center text-micro leading-5 text-zinc-600">{query ? 'No matches' : 'No threads yet'}</p>
      )}
    </nav>
  ) : (
    <nav aria-label="Conversations" className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
      {groups.map((group) => <section key={group.title}>
        <h2 className="mb-2 px-2 text-caption font-medium uppercase tracking-[.18em] text-zinc-600">{group.title}</h2>
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
                    className="min-w-0 flex-1 bg-transparent text-small text-zinc-100 outline-none"
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
                  className={`block w-full truncate rounded-lg py-2.5 pl-2.5 pr-14 text-left text-small transition-[background-color,color,box-shadow] duration-200 ease-out ${activeId === conversation.id ? 'bg-emerald-300/[0.09] font-medium text-emerald-100 shadow-[inset_2px_0_0_#ffffff]' : 'text-zinc-400 hover:bg-white/[0.045] hover:text-zinc-200'}`}
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
                    // A bare 11px icon in p-1 is about 19px, which is well under
                    // a usable touch target. The drawer is the main way a phone
                    // reaches these, so the hit area grows there and the tight
                    // desktop row is left alone.
                    className="grid size-9 place-items-center rounded-lg text-zinc-500 transition hover:bg-white/[0.08] hover:text-zinc-200 md:size-auto md:p-1"
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
                    className="grid size-9 place-items-center rounded-lg text-zinc-500 transition hover:bg-white/[0.08] hover:text-zinc-200 md:size-auto md:p-1"
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
      {groups.length === 0 && <p className="px-2 text-small leading-6 text-zinc-600">{query ? 'No matching threads.' : 'Your threads will appear here.'}</p>}
    </nav>
  )}

  <div className={`mt-4 border-t border-white/[0.06] pt-3 ${collapsed ? 'flex justify-center' : ''}`}>
    <button type="button" onClick={onOpenSettings} title="Settings" className={`flex items-center rounded-lg text-zinc-400 transition hover:bg-white/[0.045] ${collapsed ? 'size-9 justify-center' : 'min-h-9 w-full gap-2.5 px-2 py-2 text-left'}`}>
      <Settings2 size={14} className={`shrink-0 text-zinc-500 ${collapsed ? '' : ''}`} />
      {collapsed ? <span className="sr-only">Settings</span> : <span className="text-micro">Settings</span>}
    </button>
  </div>
  </aside>
}
