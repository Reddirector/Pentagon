/**
 * The settings dialog's container. After the decomposition this file owns
 * only what a dialog shell must: top-tab state, Escape-to-close, focus, and
 * the overlay. Each tab's content lives in its own module under settings/.
 */
import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import type {
  AutonomySettings,
  CommandSettings,
  Conversation,
  DocumentInfo,
  ModelInfo,
} from '../types'
import { AccountTab } from './settings/AccountTab'
import { PermissionsTab } from './settings/PermissionsTab'
import { AdvancedTab, type AdvancedSection } from './settings/advanced'

const TOP_TABS = ['Account', 'Permissions', 'Advanced'] as const
type TopTab = (typeof TOP_TABS)[number]

export function SettingsDialog({
  userId,
  models,
  serverDefaultModel,
  documents,
  threads,
  threadCount,
  onClose,
  onKeySaved,
  onDocumentDeleted,
  onRenameThread,
  onDeleteThread,
  commandSettings,
  onCommandSettingsChange,
  autonomySettings,
  onAutonomySettingChange,
  onAutonomyPresetChange,
  initialTab = 'Account',
  initialSection,
}: {
  userId: string
  models: ModelInfo[]
  serverDefaultModel: string
  documents: DocumentInfo[]
  threads: Conversation[]
  threadCount: number
  onClose: () => void
  onKeySaved: () => void
  onDocumentDeleted: (documentId: string) => void
  onRenameThread: (id: string, title: string) => void
  commandSettings: CommandSettings
  onCommandSettingsChange: (enabled: boolean) => void
  autonomySettings: AutonomySettings | null
  onAutonomySettingChange?: (category: string, level: string) => void | Promise<void>
  onAutonomyPresetChange?: (preset: string) => void | Promise<void>
  onDeleteThread: (id: string) => void
  initialTab?: TopTab
  initialSection?: AdvancedSection
}) {
  const [userTab, setUserTab] = useState<TopTab | null>(null)
  const topTab = userTab ?? initialTab ?? 'Account'
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    dialogRef.current?.focus()
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div
      className="modal-backdrop-enter fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-0 pt-0 backdrop-blur-sm sm:px-4 sm:pt-[8vh] sm:pb-[4vh]"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        className="modal-card-enter flex h-full max-h-full w-full max-w-[720px] flex-col overflow-hidden border-white/[0.1] bg-[var(--surface-panel)] shadow-[0_40px_120px_rgba(0,0,0,.6)] outline-none sm:h-auto sm:max-h-full sm:rounded-2xl sm:border"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-white/[0.07] px-4 py-3 sm:py-4 pt-[calc(0.75rem+env(safe-area-inset-top))] sm:pt-4 sm:px-6">
          <h2 className="text-body-lg font-semibold tracking-[-.01em] text-zinc-100">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200 active:scale-95"
          >
            <X size={16} />
          </button>
        </div>

        <div role="tablist" aria-label="Settings sections" className="flex shrink-0 gap-1 overflow-x-auto border-b border-white/[0.07] px-4 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
          {TOP_TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={topTab === name}
              onClick={() => setUserTab(name)}
              className={`relative shrink-0 px-3 py-2.5 text-small-lg font-medium transition duration-150 active:scale-95 ${
                topTab === name ? 'text-zinc-100' : 'text-zinc-600 hover:text-zinc-300'
              }`}
            >
              {name}
              {topTab === name && (
                <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-gradient-to-r from-emerald-400 to-white shadow-[0_0_8px_rgba(52,211,153,0.6)] animate-in fade-in" />
              )}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto pb-[calc(1.5rem+env(safe-area-inset-bottom))]">
          <div key={topTab} className="tab-content-enter">
            {topTab === 'Account' && <AccountTab userId={userId} onKeySaved={onKeySaved} />}
            {topTab === 'Permissions' && (
              <PermissionsTab
                userId={userId}
                models={models}
                serverDefaultModel={serverDefaultModel}
                autonomySettings={autonomySettings}
                onAutonomySettingChange={onAutonomySettingChange}
                onAutonomyPresetChange={onAutonomyPresetChange}
              />
            )}
            {topTab === 'Advanced' && (
              <AdvancedTab
                userId={userId}
                models={models}
                serverDefaultModel={serverDefaultModel}
                documents={documents}
                threads={threads}
                threadCount={threadCount}
                onDocumentDeleted={onDocumentDeleted}
                onRenameThread={onRenameThread}
                onDeleteThread={onDeleteThread}
                commandSettings={commandSettings}
                onCommandSettingsChange={onCommandSettingsChange}
                autonomySettings={autonomySettings}
                onAutonomySettingChange={onAutonomySettingChange}
                onAutonomyPresetChange={onAutonomyPresetChange}
                initialSection={initialSection}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
