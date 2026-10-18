/**
 * AccountMenu: First-class user account and workspace identity menu.
 * Provides quick profile inspection, workspace ID copying, and navigation
 * to Profile, API Keys, Permissions, and Settings.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  KeyRound,
  PlusCircle,
  Settings2,
  ShieldCheck,
  User,
} from 'lucide-react'
import {
  getPreferences,
  subscribePreferences,
  AVATAR_THEMES,
} from '../lib/preferences'

export function AccountMenu({
  userId,
  collapsed = false,
  onOpenSettings,
}: {
  userId: string
  collapsed?: boolean
  onOpenSettings: (tab?: 'Account' | 'Permissions' | 'Advanced') => void
}) {
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const userName = prefs.userName || 'Aditya'
  const userEmail = prefs.userEmail || 'aditya@pentagon.ai'
  const avatarTheme = AVATAR_THEMES[prefs.userAvatarColor] ?? AVATAR_THEMES.emerald

  // Derive 1-2 letter initial
  const initials = userName
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0].toUpperCase())
    .join('') || 'A'

  // Close when clicking outside or pressing Escape
  useEffect(() => {
    if (!open) return

    const handlePointerDown = (event: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    window.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  async function copyWorkspaceId() {
    try {
      await navigator.clipboard.writeText(userId)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  function handleNewWorkspace() {
    setOpen(false)
    const confirmed = window.confirm(
      'Start a new workspace?\n\nA fresh user ID will be generated. Your current conversations stay securely saved on the server under the previous ID and can be restored anytime by entering the ID in Settings.'
    )
    if (!confirmed) return
    window.localStorage.setItem('pentagon.userId', `pentagon-${crypto.randomUUID()}`)
    window.location.reload()
  }

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Popover Menu */}
      {open && (
        <div
          role="menu"
          aria-label="Account and Workspace options"
          className={`absolute z-50 rounded-2xl border border-white/[0.12] bg-[#0c0c0c]/95 p-2 shadow-[0_24px_60px_rgba(0,0,0,0.85)] backdrop-blur-2xl ring-1 ring-white/[0.05] transition-all duration-150 animate-in fade-in zoom-in-95 ${
            collapsed
              ? 'bottom-0 left-[calc(100%+12px)] w-72'
              : 'bottom-[calc(100%+10px)] left-0 w-full min-w-[260px]'
          }`}
        >
          {/* User & Workspace Summary */}
          <div className="border-b border-white/[0.08] p-2.5 pb-3">
            <div className="flex items-center gap-3">
              <div
                className={`grid size-10 shrink-0 place-items-center rounded-xl border ${avatarTheme.border} ${avatarTheme.bg} font-semibold text-small ${avatarTheme.text} shadow-inner`}
              >
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-small font-semibold text-zinc-100">{userName}</span>
                  <span className="rounded-md border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-emerald-300">
                    Pro
                  </span>
                </div>
                <div className="truncate text-micro text-zinc-400">{userEmail}</div>
              </div>
            </div>

            {/* Workspace ID pill */}
            <div className="mt-2.5 flex items-center justify-between gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.025] px-2.5 py-1.5">
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Workspace</div>
                <div className="truncate font-mono text-[11px] text-zinc-300">{userId}</div>
              </div>
              <button
                type="button"
                onClick={copyWorkspaceId}
                title="Copy Workspace ID"
                className="grid size-6 shrink-0 place-items-center rounded-md text-zinc-400 transition hover:bg-white/[0.08] hover:text-zinc-100"
              >
                {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
              </button>
            </div>
          </div>

          {/* Quick Menu Items */}
          <div className="space-y-0.5 pt-1.5">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onOpenSettings('Account')
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-small text-zinc-300 transition hover:bg-white/[0.06] hover:text-zinc-100"
            >
              <User size={14} className="text-zinc-400" />
              <span>Profile & Identity</span>
            </button>

            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onOpenSettings('Account')
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-small text-zinc-300 transition hover:bg-white/[0.06] hover:text-zinc-100"
            >
              <KeyRound size={14} className="text-zinc-400" />
              <span>API Keys & NIM</span>
            </button>

            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onOpenSettings('Permissions')
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-small text-zinc-300 transition hover:bg-white/[0.06] hover:text-zinc-100"
            >
              <ShieldCheck size={14} className="text-emerald-400" />
              <span>Safety & Permissions</span>
            </button>

            <button
              type="button"
              role="menuitem"
              onClick={handleNewWorkspace}
              className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-small text-zinc-300 transition hover:bg-white/[0.06] hover:text-zinc-100"
            >
              <PlusCircle size={14} className="text-zinc-400" />
              <span>Start New Workspace</span>
            </button>
          </div>

          {/* Footer divider and general settings */}
          <div className="mt-1.5 border-t border-white/[0.08] pt-1.5">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onOpenSettings('Advanced')
              }}
              className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-left text-small text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-100"
            >
              <div className="flex items-center gap-2.5">
                <Settings2 size={14} className="text-zinc-500" />
                <span>All Settings</span>
              </div>
              <span className="font-mono text-[10px] text-zinc-500">⌘,</span>
            </button>
          </div>
        </div>
      )}

      {/* Trigger Button */}
      {collapsed ? (
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-label={`Account: ${userName}`}
          aria-haspopup="menu"
          aria-expanded={open}
          title={`${userName} (${userEmail})`}
          className={`group relative grid size-10 place-items-center rounded-xl border ${avatarTheme.border} ${avatarTheme.bg} transition hover:scale-105 hover:ring-2 ${avatarTheme.ring}`}
        >
          <span className={`text-small font-semibold ${avatarTheme.text}`}>{initials}</span>
          <span className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-[#090909] bg-emerald-400" />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-label={`Account: ${userName}`}
          aria-haspopup="menu"
          aria-expanded={open}
          className={`group flex w-full items-center gap-2.5 rounded-xl border border-white/[0.06] bg-white/[0.02] p-2 text-left transition hover:border-white/[0.12] hover:bg-white/[0.05] ${
            open ? 'border-white/[0.15] bg-white/[0.06]' : ''
          }`}
        >
          <div
            className={`grid size-8 shrink-0 place-items-center rounded-lg border ${avatarTheme.border} ${avatarTheme.bg} text-caption font-semibold ${avatarTheme.text}`}
          >
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-micro font-medium text-zinc-200 group-hover:text-white">
              {userName}
            </div>
            <div className="truncate text-[11px] text-zinc-500">
              {prefs.workspaceName || 'Personal Workspace'}
            </div>
          </div>
          <div className="shrink-0 text-zinc-500 transition group-hover:text-zinc-300">
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        </button>
      )}
    </div>
  )
}
