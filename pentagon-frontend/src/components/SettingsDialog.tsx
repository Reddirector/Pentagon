import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { AlertTriangle, Check, Copy, LockKeyhole, MapPin, MoonStar, Pencil, Sun, Trash2, Waves, X } from 'lucide-react'
import { getAmbientMode, setAmbientMode, subscribeAmbient } from '../lib/ambient'
import type { AmbientMode } from '../lib/ambient'
import {
  APPEARANCES,
  DENSITIES,
  getPreferences,
  resetPreferences,
  setAppearance,
  setContrast,
  setDefaultModel,
  setDensity,
  setSidebarCollapsed,
  setTextSize,
  setWorkspaceName,
  subscribePreferences,
  TEXT_SIZES,
} from '../lib/preferences'
import type { Appearance, Contrast, Density, TextSize } from '../lib/preferences'
import { getSupabase, isSupabaseConfigured } from '../lib/supabase'
import { apiRequest, getApiBase, getLocalUserId, setApiBase } from '../api'
import type { CommandSettings, Conversation, DocumentInfo, MemoryInfo, ModelInfo, SkillInfo } from '../types'
import { PermissionPanel } from './PermissionPanel'
import { applyAutonomyPreset, putAutonomySetting, fetchAuditLog } from '../api'
import type { AutonomySettings, AuditLogEntry } from '../types'

const AMBIENT_OPTIONS: { mode: AmbientMode; label: string; description: string; icon: typeof Sun }[] = [
  { mode: 'full', label: 'Full', description: 'Aurora, orbit rings, a twinkling constellation, grain and a vignette.', icon: Sun },
  { mode: 'calm', label: 'Calm', description: 'Half the stars, slower drift, no long rotations.', icon: Waves },
  { mode: 'off', label: 'Off', description: 'A plain static background. Nothing moves.', icon: MoonStar },
]

const SHORTCUTS: [string, string][] = [
  ['⌘ K', 'Command palette'],
  ['/', 'Focus the composer'],
  ['⌘ ⇧ O', 'New thread'],
  ['Alt ↑ / ↓', 'Jump between answers'],
  ['Esc', 'Close a dialog'],
]

const TOP_TABS = ['Account', 'Permissions', 'Advanced'] as const
type TopTab = (typeof TOP_TABS)[number]

const ADVANCED_SECTIONS = ['Skills', 'Commands', 'Data', 'Appearance', 'Model', 'Audit log', 'About'] as const
type AdvancedSection = (typeof ADVANCED_SECTIONS)[number]

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-white/[0.06] px-4 py-5 sm:px-6 last:border-b-0">
      <h3 className="text-micro font-medium uppercase tracking-[.16em] text-zinc-500">{title}</h3>
      {hint && <p className="mt-1.5 text-small leading-5 text-zinc-600">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Choice({
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

function ThreadRow({
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

const inputClass =
  'h-9 w-full rounded-lg border border-white/[0.09] bg-white/[0.03] px-3 text-body text-zinc-100 outline-none transition placeholder:text-zinc-700 focus:border-white/30'

// Kept separate from inputClass on purpose: adding bg-black/text-white on top of
// the input utilities would lose to them in the generated stylesheet, where
// source order decides, not the order written in the attribute.
const selectClass =
  'h-9 w-full cursor-pointer rounded-lg border border-white/[0.12] bg-black px-3 text-body text-white outline-none transition focus:border-white/30'

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
}) {
  const [topTab, setTopTab] = useState<TopTab>('Account')
  const [advancedSection, setAdvancedSection] = useState<AdvancedSection>('Skills')
  const dialogRef = useRef<HTMLDivElement>(null)
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  // Subscribed rather than read once, so the ambient radio repaints when the
  // mode changes (including the session-only auto-downgrade).
  const ambientMode = useSyncExternalStore(subscribeAmbient, getAmbientMode)

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    dialogRef.current?.focus()
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const [copied, setCopied] = useState(false)

  const [apiBaseDraft, setApiBaseDraft] = useState(() => getApiBase())
  const [testingApi, setTestingApi] = useState(false)
  const [apiBaseTest, setApiBaseTest] = useState<{ ok: boolean; message: string } | null>(null)

  // The value has to be saved before probing it, otherwise the request would
  // still go to the old origin. Reloading afterwards is deliberate: every
  // request the app makes is rooted at this value from first paint.
  async function saveApiBase(): Promise<void> {
    setApiBase(apiBaseDraft)
    window.location.reload()
  }

  async function testApiBase(): Promise<void> {
    setTestingApi(true)
    setApiBaseTest(null)
    const candidate = apiBaseDraft.trim().replace(/\/+$/, '')
    try {
      const response = await fetch(`${candidate}/api/models?user_id=${encodeURIComponent(userId)}`)
      if (response.ok) setApiBaseTest({ ok: true, message: 'Reachable.' })
      else if (response.status === 404) setApiBaseTest({ ok: true, message: 'Reachable (no key stored yet).' })
      else setApiBaseTest({ ok: false, message: `Answered ${response.status}.` })
    } catch {
      setApiBaseTest({ ok: false, message: 'Could not reach that address.' })
    } finally {
      setTestingApi(false)
    }
  }
  async function copyId() {
    try {
      await navigator.clipboard.writeText(userId)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  function newWorkspace() {
    const ok = window.confirm(
      'Start a new workspace?\n\nA new id is generated in this browser. Existing threads stay on the server under the old id and will no longer be listed here. To recover them, paste the old id back with the button below.',
    )
    if (!ok) return
    window.localStorage.setItem('pentagon.userId', `pentagon-${crypto.randomUUID()}`)
    window.location.reload()
  }

  const [keyInput, setKeyInput] = useState('')
  const [keyState, setKeyState] = useState<'idle' | 'checking' | 'valid' | 'invalid'>('idle')
  const [keyMessage, setKeyMessage] = useState('')
  const [savingKey, setSavingKey] = useState(false)

  async function checkKey() {
    const value = keyInput.trim()
    if (!value) return
    setKeyState('checking')
    setKeyMessage('Asking NVIDIA whether the key works…')
    try {
      const result = await apiRequest<{ valid: boolean; reason?: string }>('/api/keys/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: value }),
      })
      if (result.valid) {
        setKeyState('valid')
        setKeyMessage('Key accepted by NVIDIA.')
      } else {
        setKeyState('invalid')
        setKeyMessage(result.reason || 'NVIDIA rejected this key.')
      }
    } catch (cause) {
      setKeyState('invalid')
      setKeyMessage(cause instanceof Error ? cause.message : 'Could not reach the backend.')
    }
  }

  async function saveKey() {
    if (keyState !== 'valid' || savingKey) return
    setSavingKey(true)
    setKeyMessage('Storing…')
    try {
      await apiRequest('/api/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, api_key: keyInput.trim() }),
      })
      setKeyInput('')
      setKeyState('idle')
      setKeyMessage('Saved. It is encrypted on the server and reused for every request.')
      onKeySaved()
    } catch (cause) {
      setKeyMessage(cause instanceof Error ? cause.message : 'Could not store the key.')
    } finally {
      setSavingKey(false)
    }
  }

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [authMode, setAuthMode] = useState<'signin' | 'signup'>('signin')
  const [authBusy, setAuthBusy] = useState(false)
  const [authMessage, setAuthMessage] = useState('')
  // Deleting a document used to fail silently, so a broken request looked
  // exactly like a click that did nothing.
  const [documentError, setDocumentError] = useState('')
  // Memories are loaded once when the dialog opens: null means "still
  // loading", an empty array means the store is genuinely empty.
  const [memories, setMemories] = useState<MemoryInfo[] | null>(null)
  const [memoryError, setMemoryError] = useState('')
  // Skills load when the dialog opens, like memories: null = loading.
  const [skills, setSkills] = useState<SkillInfo[] | null>(null)
  const [skillError, setSkillError] = useState('')
  const [skillNotice, setSkillNotice] = useState('')
  const [skillBusy, setSkillBusy] = useState(false)
  const [skillDraft, setSkillDraft] = useState({
    name: '',
    description: '',
    triggers: '',
    body: '',
    risk: 'read',
  })

  useEffect(() => {
    let active = true
    void apiRequest<SkillInfo[]>(`/api/skills?user_id=${encodeURIComponent(userId)}`)
      .then((rows) => {
        if (active) setSkills(rows)
      })
      .catch((cause) => {
        if (!active) return
        setSkillError(cause instanceof Error ? cause.message : 'Could not load skills.')
        setSkills([])
      })
    return () => {
      active = false
    }
  }, [userId])

  async function toggleSkill(skill: SkillInfo, enabled: boolean) {
    setSkillError('')
    setSkillNotice('')
    try {
      await apiRequest(`/api/skills/${encodeURIComponent(skill.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, enabled }),
      })
      setSkills((rows) =>
        (rows ?? []).map((row) => (row.id === skill.id ? { ...row, enabled } : row)),
      )
    } catch (cause) {
      setSkillError(
        cause instanceof Error ? cause.message : 'Could not update that skill.',
      )
    }
  }

  async function addSkill(event: React.FormEvent) {
    event.preventDefault()
    if (skillBusy) return
    setSkillError('')
    setSkillNotice('')
    const triggers = skillDraft.triggers
      .split(',')
      .map((trigger) => trigger.trim())
      .filter(Boolean)
    if (!skillDraft.name.trim() || !skillDraft.description.trim() || triggers.length === 0 || !skillDraft.body.trim()) {
      setSkillError('Name, description, at least one trigger and an instruction body are required.')
      return
    }
    if (skillDraft.description.trim().length > 200) {
      setSkillError('The description is capped at 200 characters — it is the only text the model sees before loading a skill.')
      return
    }
    setSkillBusy(true)
    try {
      const created = await apiRequest<SkillInfo>('/api/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          name: skillDraft.name.trim(),
          description: skillDraft.description.trim(),
          triggers,
          risk_category: skillDraft.risk,
          body: skillDraft.body.trim(),
        }),
      })
      setSkills((rows) => [created, ...(rows ?? [])])
      setSkillDraft({ name: '', description: '', triggers: '', body: '', risk: 'read' })
      setSkillNotice(`Added ${created.name}. It applies from your next message — no restart.`)
    } catch (cause) {
      setSkillError(cause instanceof Error ? cause.message : 'Could not save the skill.')
    } finally {
      setSkillBusy(false)
    }
  }

  useEffect(() => {
    let active = true
    void apiRequest<MemoryInfo[]>(`/api/memories?user_id=${encodeURIComponent(userId)}`)
      .then((rows) => {
        if (active) setMemories(rows)
      })
      .catch((cause) => {
        if (!active) return
        setMemoryError(
          cause instanceof Error ? cause.message : 'Could not load memories.',
        )
        setMemories([])
      })
    return () => {
      active = false
    }
  }, [userId])

  async function removeMemory(memoryId: string) {
    setMemoryError('')
    try {
      await apiRequest(
        `/api/memories/${encodeURIComponent(memoryId)}?user_id=${encodeURIComponent(userId)}`,
        { method: 'DELETE' },
      )
      setMemories((rows) => (rows ?? []).filter((row) => row.id !== memoryId))
    } catch (cause) {
      setMemoryError(
        cause instanceof Error ? cause.message : 'Could not delete that memory.',
      )
    }
  }
  const [sessionEmail, setSessionEmail] = useState<string | null>(null)

  useEffect(() => {
    const client = getSupabase()
    if (!client) return
    let active = true
    void client.auth.getSession().then(({ data }) => {
      if (active) setSessionEmail(data.session?.user.email ?? null)
    })
    const { data: listener } = client.auth.onAuthStateChange((_event, next) => {
      setSessionEmail(next?.user?.email ?? null)
    })
    return () => {
      active = false
      listener.subscription.unsubscribe()
    }
  }, [])

  async function submitAuth(event: React.FormEvent) {
    event.preventDefault()
    const client = getSupabase()
    if (!client) return
    setAuthBusy(true)
    setAuthMessage('')
    try {
      if (authMode === 'signup') {
        const { error } = await client.auth.signUp({ email: email.trim(), password })
        if (error) throw error
        setAuthMessage('Account created. Sign in below if confirmation is enabled.')
      } else {
        const { error } = await client.auth.signInWithPassword({ email: email.trim(), password })
        if (error) throw error
        setAuthMessage('Signed in.')
      }
      setPassword('')
    } catch (cause) {
      setAuthMessage(cause instanceof Error ? cause.message : 'Authentication failed.')
    } finally {
      setAuthBusy(false)
    }
  }

  async function signOut() {
    const client = getSupabase()
    if (!client) return
    setAuthBusy(true)
    await client.auth.signOut()
    setAuthMessage('')
    setAuthBusy(false)
  }

  async function removeDocument(documentId: string) {
    setDocumentError('')
    try {
      // remove_document is scoped by owner, so it needs the same user_id the
      // upload and list calls send. Without it the request is a 422 and the
      // document silently refuses to delete.
      await apiRequest(
        `/api/documents/${encodeURIComponent(documentId)}?user_id=${encodeURIComponent(getLocalUserId())}`,
        { method: 'DELETE' },
      )
      onDocumentDeleted(documentId)
    } catch (cause) {
      setDocumentError(
        cause instanceof Error ? cause.message : 'Could not delete that document.',
      )
    }
  }

  const [commandBusy, setCommandBusy] = useState(false)
  const [commandError, setCommandError] = useState('')
  const [autonomyBusy, setAutonomyBusy] = useState(false)
  const [auditRows, setAuditRows] = useState<AuditLogEntry[]>([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditCategory, setAuditCategory] = useState('')
  const [auditDecision, setAuditDecision] = useState('')

  useEffect(() => {
    if (advancedSection !== 'Audit log') return
    let active = true
    async function load() {
      setAuditLoading(true)
      try {
        const { rows } = await fetchAuditLog(
          userId,
          80,
          undefined,
          auditCategory || undefined,
          auditDecision || undefined,
        )
        if (active) setAuditRows(rows)
      } catch {
        if (active) setAuditRows([])
      } finally {
        if (active) setAuditLoading(false)
      }
    }
    void load()
    return () => { active = false }
  }, [advancedSection, userId, auditCategory, auditDecision])

  async function setCommandsEnabled(enabled: boolean) {
    if (commandBusy) return
    setCommandBusy(true)
    setCommandError('')
    try {
      const result = await apiRequest<CommandSettings>(
        `/api/commands/settings?user_id=${encodeURIComponent(userId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled }),
        },
      )
      onCommandSettingsChange(result.enabled)
    } catch (cause) {
      setCommandError(cause instanceof Error ? cause.message : 'Could not change that setting.')
    } finally {
      setCommandBusy(false)
    }
  }

  async function handleCategoryChange(category: string, level: string) {
    if (!onAutonomySettingChange) return
    setAutonomyBusy(true)
    try {
      await putAutonomySetting(userId, category, level)
      await onAutonomySettingChange(category, level)
    } catch {
      // Best-effort: the parent re-fetches settings on change, so a failed
      // write does not leave the panel stale.
    } finally {
      setAutonomyBusy(false)
    }
  }

  async function handlePresetChange(preset: string) {
    if (!onAutonomyPresetChange) return
    setAutonomyBusy(true)
    try {
      const next = await applyAutonomyPreset(userId, preset)
      await onAutonomyPresetChange(preset)
      // Refresh local copy so the panel shows the freshly saved state.
      if (onAutonomySettingChange) {
        for (const [category, level] of Object.entries(next.settings as Record<string, string>)) {
          await onAutonomySettingChange(category, level)
        }
      }
    } catch {
      // Best-effort: the parent re-fetches settings on change.
    } finally {
      setAutonomyBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-0 pt-0 backdrop-blur-sm sm:px-4 sm:pt-[8vh] sm:pb-[4vh]"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        className="panel-enter flex h-full max-h-full w-full max-w-[720px] flex-col overflow-hidden border-white/[0.1] bg-[var(--surface-panel)] shadow-[0_40px_120px_rgba(0,0,0,.6)] outline-none sm:h-auto sm:max-h-full sm:rounded-2xl sm:border"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-white/[0.07] px-4 py-4 sm:px-6">
          <h2 className="text-body-lg font-semibold tracking-[-.01em] text-zinc-100">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-lg p-1 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <X size={15} />
          </button>
        </div>

        <div role="tablist" aria-label="Settings sections" className="flex shrink-0 gap-1 overflow-x-auto border-b border-white/[0.07] px-4">
          {TOP_TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={topTab === name}
              onClick={() => setTopTab(name)}
              className={`relative shrink-0 px-3 py-2.5 text-small-lg font-medium transition ${
                topTab === name ? 'text-zinc-100' : 'text-zinc-600 hover:text-zinc-300'
              }`}
            >
              {name}
              {topTab === name && <span className="absolute inset-x-2 -bottom-px h-px bg-white" />}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {topTab === 'Account' && (
            <>
              <Section title="Workspace" hint="Threads and documents are scoped to this id. It is generated in this browser and sent with every request.">
                <div className="space-y-3">
                  <label className="block">
                    <span className="mb-1.5 block text-micro-sm text-zinc-500">Name</span>
                    <input
                      value={prefs.workspaceName}
                      onChange={(event) => setWorkspaceName(event.target.value)}
                      maxLength={40}
                      className={inputClass}
                      aria-label="Workspace name"
                    />
                  </label>
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-small text-zinc-500">
                      {userId}
                    </code>
                    <button
                      type="button"
                      onClick={copyId}
                      className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.09] px-3 text-small text-zinc-400 transition hover:bg-white/[0.05] hover:text-zinc-200"
                    >
                      {copied ? <Check size={13} /> : <Copy size={13} />}
                      {copied ? 'Copied' : 'Copy'}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={newWorkspace}
                    className="flex items-center gap-1.5 text-small text-zinc-600 transition hover:text-zinc-300"
                  >
                    <AlertTriangle size={12} /> Start a new workspace
                  </button>
                </div>
              </Section>

              <Section
                title="Backend"
                hint="Where this app sends its requests. Leave empty to use this same origin, which is what the desktop app and the dev server do. Phones and tablets need the full address of your Pentagon backend, for example http://192.168.1.20:8000."
              >
                <div className="space-y-3">
                  <label className="block">
                    <span className="mb-1.5 block text-micro-sm text-zinc-500">Server address</span>
                    <input
                      type="url"
                      inputMode="url"
                      autoCapitalize="off"
                      autoCorrect="off"
                      spellCheck={false}
                      value={apiBaseDraft}
                      onChange={(event) => setApiBaseDraft(event.target.value)}
                      placeholder={import.meta.env.VITE_PENTAGON_API_BASE || 'Same origin'}
                      className={inputClass}
                      aria-label="Backend server address"
                    />
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={saveApiBase}
                      className="flex h-9 items-center rounded-lg border border-white/[0.09] px-3 text-small text-zinc-300 transition hover:bg-white/[0.05]"
                    >
                      Save &amp; reload
                    </button>
                    <button
                      type="button"
                      onClick={() => testApiBase()}
                      disabled={testingApi}
                      className="flex h-9 items-center rounded-lg border border-white/[0.09] px-3 text-small text-zinc-400 transition hover:bg-white/[0.05] disabled:opacity-50"
                    >
                      Test connection
                    </button>
                    {apiBaseTest && (
                      <span className={apiBaseTest.ok ? 'text-small text-emerald-300' : 'text-small text-rose-300'}>
                        {apiBaseTest.message}
                      </span>
                    )}
                  </div>
                </div>
              </Section>

              <Section
                title="NVIDIA API key"
                hint="Stored encrypted on the backend and reused for every request. If the server has a key configured, this is optional."
              >
                <div className="space-y-2.5">
                  <input
                    type="password"
                    value={keyInput}
                    onChange={(event) => {
                      setKeyInput(event.target.value)
                      setKeyState('idle')
                      setKeyMessage('')
                    }}
                    placeholder="nvapi-…"
                    autoComplete="off"
                    spellCheck={false}
                    className={inputClass}
                    aria-label="NVIDIA API key"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={checkKey}
                      disabled={!keyInput.trim() || keyState === 'checking'}
                      className="h-9 rounded-lg border border-white/[0.09] px-3.5 text-small text-zinc-300 transition hover:bg-white/[0.05] disabled:opacity-40"
                    >
                      {keyState === 'checking' ? 'Checking…' : 'Validate'}
                    </button>
                    <button
                      type="button"
                      onClick={saveKey}
                      disabled={keyState !== 'valid' || savingKey}
                      className="h-9 rounded-lg bg-white px-3.5 text-small font-medium text-black transition hover:bg-zinc-200 disabled:opacity-40"
                    >
                      {savingKey ? 'Saving…' : 'Save key'}
                    </button>
                    {keyMessage && (
                      <span className={`text-small ${keyState === 'invalid' ? 'text-zinc-400' : 'text-zinc-500'}`}>
                        {keyMessage}
                      </span>
                    )}
                  </div>
                </div>
              </Section>

              <Section
                title="Cloud account"
                hint="Optional. Signing in verifies who you are with Supabase. Threads still live in this browser's workspace until sync is turned on."
              >
                {!isSupabaseConfigured ? (
                  <p className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-3 text-small leading-[1.6] text-zinc-600">
                    Not configured. Set <code className="text-zinc-400">VITE_SUPABASE_URL</code> and{' '}
                    <code className="text-zinc-400">VITE_SUPABASE_ANON_KEY</code> in{' '}
                    <code className="text-zinc-400">pentagon-frontend/.env</code>, then restart the dev server. Sign-in
                    needs no tables; the <code className="text-zinc-400">supabase/schema.sql</code> tables are only for
                    future sync. Everything else on this page works without it.
                  </p>
                ) : sessionEmail ? (
                  <div className="flex items-center gap-3">
                    <span className="min-w-0 flex-1 truncate text-body text-zinc-200">{sessionEmail}</span>
                    <button
                      type="button"
                      onClick={signOut}
                      disabled={authBusy}
                      className="h-9 shrink-0 rounded-lg border border-white/[0.09] px-3.5 text-small text-zinc-300 transition hover:bg-white/[0.05] disabled:opacity-40"
                    >
                      Sign out
                    </button>
                  </div>
                ) : (
                  <form onSubmit={submitAuth} className="space-y-2.5">
                    <div className="grid gap-2.5 sm:grid-cols-2">
                      <input
                        type="email"
                        required
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        placeholder="you@example.com"
                        autoComplete="email"
                        className={inputClass}
                        aria-label="Email"
                      />
                      <input
                        type="password"
                        required
                        minLength={6}
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        placeholder="Password"
                        autoComplete={authMode === 'signin' ? 'current-password' : 'new-password'}
                        className={inputClass}
                        aria-label="Password"
                      />
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="submit"
                        disabled={authBusy}
                        className="h-9 rounded-lg bg-white px-3.5 text-small font-medium text-black transition hover:bg-zinc-200 disabled:opacity-40"
                      >
                        {authBusy ? 'Working…' : authMode === 'signin' ? 'Sign in' : 'Create account'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setAuthMode(authMode === 'signin' ? 'signup' : 'signin')
                          setAuthMessage('')
                        }}
                        className="text-small text-zinc-600 transition hover:text-zinc-300"
                      >
                        {authMode === 'signin' ? 'Need an account?' : 'Already registered?'}
                      </button>
                      {authMessage && <span className="text-small text-zinc-500">{authMessage}</span>}
                    </div>
                  </form>
                )}
              </Section>
            </>
          )}

          {topTab === 'Permissions' && (
            <Section
              title="Default model"
              hint="Used for new threads. An existing thread keeps the model it was started with."
            >
              <div className="space-y-2.5">
                <select
                  value={prefs.defaultModel || ''}
                  onChange={(event) => setDefaultModel(event.target.value)}
                  className={selectClass}
                  aria-label="Default model"
                >
                  <option value="" className="bg-black text-white">
                    Server default{serverDefaultModel ? ` (${serverDefaultModel})` : ''}
                  </option>
                  {models.map((model) => (
                    <option key={model.id} value={model.id} className="bg-black text-white">
                      {model.id}
                    </option>
                  ))}
                </select>
                <p className="text-small leading-[1.6] text-zinc-600">
                  {models.length} model{models.length === 1 ? '' : 's'} available on this server. Reasoning models can take
                  a couple of minutes before the first token.
                </p>
              </div>
            </Section>
          )}

          {topTab === 'Permissions' && (
            autonomySettings ? (
              <PermissionPanel
                settings={autonomySettings}
                busy={autonomyBusy}
                onChange={(category, level) => void handleCategoryChange(category, level)}
                onPresetChange={onAutonomyPresetChange ? (preset) => void handlePresetChange(preset) : undefined}
              />
            ) : (
              <p className="text-small text-zinc-500">Loading permissions…</p>
            )
          )}

          {topTab === 'Advanced' && (
            <div className="min-h-[240px]">
              {/* Section picker: one extra click before anything inside Advanced is shown. */}
              <div className="flex gap-1 rounded-xl border border-white/[0.09] bg-white/[0.02] p-1" role="tablist" aria-label="Advanced sections">
                {ADVANCED_SECTIONS.map((name) => (
                  <button
                    key={name}
                    type="button"
                    role="tab"
                    aria-selected={advancedSection === name}
                    onClick={() => setAdvancedSection(name)}
                    className={`rounded-lg px-3 py-1.5 text-small font-medium transition ${
                      advancedSection === name
                        ? 'bg-white/[0.06] text-zinc-100'
                        : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    {name}
                  </button>
                ))}
              </div>

              <div className="mt-4 space-y-4">
                {advancedSection === 'Skills' && (
                  <>
                    <Section
                      title="Skills"
                      hint="Capability packs the model can draw on. Every skill's one-line description is always visible; the full instructions load only for a request that matches, for that turn only — never into saved history."
                    >
                      {skillError && <p className="mb-2 text-small text-amber-300/90">{skillError}</p>}
                      {skills === null ? (
                        <p className="text-small text-zinc-600">Loading…</p>
                      ) : skills.length === 0 ? (
                        <p className="text-small text-zinc-600">Nothing here yet.</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {skills.map((skill) => (
                            <li
                              key={skill.id}
                              className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
                            >
                              <span className="min-w-0 flex-1">
                                <span className="text-small-lg text-zinc-300">{skill.name}</span>
                                <span className="ml-2 rounded border border-white/[0.1] px-1.5 py-0.5 text-micro text-zinc-500">
                                  {skill.source === 'public' ? 'shipped' : 'yours'}
                                </span>
                                <span className="mt-0.5 block text-micro leading-[1.55] text-zinc-600">
                                  {skill.description}
                                </span>
                                <span className="mt-1 block text-micro text-zinc-700">
                                  Triggers: {skill.triggers.join(', ') || '—'}
                                </span>
                              </span>
                              <button
                                type="button"
                                role="switch"
                                aria-checked={skill.enabled}
                                aria-label={`${skill.enabled ? 'Disable' : 'Enable'} ${skill.name}`}
                                onClick={() => void toggleSkill(skill, !skill.enabled)}
                                className="flex shrink-0 items-center gap-2 text-micro text-zinc-600"
                              >
                                <span aria-hidden="true" className="flex h-5 w-9 items-center rounded-full p-0.5 transition">
                                  <span
                                    className={`size-4 rounded-full transition-transform ${
                                      skill.enabled ? 'translate-x-4 bg-emerald-300' : 'bg-white/[0.18]'
                                    }`}
                                  />
                                </span>
                                {skill.enabled ? 'On' : 'Off'}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </Section>

                    <Section
                      title="Add a skill"
                      hint="Writes skills/user/<name>/SKILL.md on the server. It is live from your next message — no restart."
                    >
                      <form onSubmit={(event) => void addSkill(event)} className="space-y-3">
                        <input
                          value={skillDraft.name}
                          onChange={(event) => setSkillDraft({ ...skillDraft, name: event.target.value })}
                          placeholder="Name, e.g. Meeting notes"
                          maxLength={80}
                          className={inputClass}
                          aria-label="Skill name"
                        />
                        <input
                          value={skillDraft.description}
                          onChange={(event) => setSkillDraft({ ...skillDraft, description: event.target.value })}
                          placeholder="What it covers and exactly when to use it (under 200 characters)"
                          maxLength={200}
                          className={inputClass}
                          aria-label="Skill description"
                        />
                        <input
                          value={skillDraft.triggers}
                          onChange={(event) => setSkillDraft({ ...skillDraft, triggers: event.target.value })}
                          placeholder="Trigger keywords, comma separated — e.g. standup, action items"
                          className={inputClass}
                          aria-label="Trigger keywords"
                        />
                        <textarea
                          value={skillDraft.body}
                          onChange={(event) => setSkillDraft({ ...skillDraft, body: event.target.value })}
                          placeholder={'Instructions, step by step. Written like a briefing for a competent colleague:\n\n1. …\n2. …'}
                          rows={7}
                          className="w-full rounded-lg border border-white/[0.09] bg-white/[0.03] px-3 py-2 text-body leading-6 text-zinc-100 outline-none transition placeholder:text-zinc-700 focus:border-white/30"
                          aria-label="Skill instructions"
                        />
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="submit"
                            disabled={skillBusy}
                            className="h-9 rounded-lg bg-white/[0.12] px-3.5 text-small font-medium text-zinc-100 transition hover:bg-white/[0.18] disabled:opacity-50"
                          >
                            {skillBusy ? 'Adding…' : 'Add skill'}
                          </button>
                          {skillNotice && (
                            <p className="text-small text-emerald-300/90">{skillNotice}</p>
                          )}
                        </div>
                        {skillError && <p className="text-small text-amber-300/90">{skillError}</p>}
                      </form>
                    </Section>
                  </>
                )}

                {advancedSection === 'Commands' && (
                  <>
                    <Section
                      title="Command tool"
                      hint="Lets Pentagon run CLI commands on this machine so it can build, test and inspect your project instead of only describing what to do."
                    >
                      {!commandSettings.available ? (
                        <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3.5 py-3 text-small leading-6 text-zinc-500">
                          This server does not offer the command tool. Set{' '}
                          <code className="font-mono text-zinc-400">COMMAND_TOOL_ENABLED=true</code> in the
                          backend environment and restart it to make it available.
                        </p>
                      ) : (
                        <>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={commandSettings.enabled}
                            disabled={commandBusy}
                            onClick={() => void setCommandsEnabled(!commandSettings.enabled)}
                            className="flex w-full items-start gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-3 text-left transition hover:border-white/15 disabled:opacity-50"
                          >
                            <span
                              aria-hidden="true"
                              className={`mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition ${
                                commandSettings.enabled ? 'bg-emerald-300' : 'bg-white/[0.12]'
                              }`}
                            >
                              <span
                                className={`size-4 rounded-full bg-black transition-transform ${
                                  commandSettings.enabled ? 'translate-x-4' : ''
                                }`}
                              />
                            </span>
                            <span className="min-w-0">
                              <span className="block text-body font-medium text-zinc-100">
                                Let Pentagon run commands
                              </span>
                              <span className="mt-0.5 block text-micro-sm leading-[1.55] text-zinc-600">
                                {commandSettings.enabled
                                  ? 'On. Read-only commands run immediately; anything else asks you first.'
                                  : 'Off. The model is not offered a command tool at all.'}
                              </span>
                            </span>
                          </button>
                          {commandError && (
                            <p className="mt-2 text-small text-amber-300/90">{commandError}</p>
                          )}
                        </>
                      )}
                    </Section>

                    <Section title="How a command is treated" hint="The rule is that nothing runs unless you would be comfortable typing it yourself.">
                      <p className="text-small leading-6 text-zinc-500">
                        Read-only commands run by themselves; anything that changes your machine or
                        reaches outside it asks you first. Commands that need{' '}
                        <code className="font-mono text-[0.92em]">sudo</code> or another user account are
                        refused outright, approved or not.
                      </p>
                    </Section>

                    <Section
                      title="Your desktop"
                      hint="Alongside the command line, it can drive the desktop: open and close applications, focus windows, take screenshots, change the volume, control playback, send notifications, lock the screen, switch dark mode and manage power."
                    >
                      {commandSettings.desktop_available ? (
                        <>
                          <ul className="space-y-2.5 text-small leading-6 text-zinc-500">
                            <li className="flex gap-2.5">
                              <span className="mt-1 shrink-0 text-zinc-500">·</span>
                              <span>
                                <span className="text-zinc-300">Listing windows runs by itself.</span> Seeing
                                which windows are open changes nothing, so it does not interrupt you.
                              </span>
                            </li>
                            <li className="flex gap-2.5">
                              <LockKeyhole size={13} className="mt-1 shrink-0 text-zinc-500" />
                              <span>
                                <span className="text-zinc-300">Everything else asks first.</span> Closing an
                                app, locking the screen or shutting the machine down are shown to you as a
                                plain description, not a command line, and do nothing if you decline.
                              </span>
                            </li>
                            <li className="flex gap-2.5">
                              <AlertTriangle size={13} className="mt-1 shrink-0 text-zinc-500" />
                              <span>
                                <span className="text-zinc-300">A fixed set, no shell.</span> These are named
                                actions, not commands you can talk into. There is no way to phrase an
                                instruction that turns into a shell command line.
                              </span>
                            </li>
                          </ul>
                          <p className="mt-3 text-micro leading-5 text-zinc-600">
                            It closes a window by matching part of its title, so check what it picked before
                            saying yes.
                          </p>
                        </>
                      ) : (
                        <p className="text-small leading-6 text-zinc-500">
                          Desktop control is switched off on the server, so the model cannot open or close
                          anything on this machine. Command line access is unaffected.
                        </p>
                      )}
                    </Section>

                    <Section
                      title="Where it thinks you are"
                      hint="For questions that depend on it — what is near me, what time is it there — it can look up your approximate position. It does this only when an answer actually needs it, never in the background."
                    >
                      {commandSettings.location_available ? (
                        <>
                          <ul className="space-y-2.5 text-small leading-6 text-zinc-500">
                            <li className="flex gap-2.5">
                              <MapPin size={13} className="mt-1 shrink-0 text-zinc-500" />
                              <span>
                                <span className="text-zinc-300">Your browser is asked first.</span> The app
                                window shows you the usual permission prompt. If you decline, it falls back
                                to a coarse estimate from your network connection.
                              </span>
                            </li>
                            <li className="flex gap-2.5">
                              <AlertTriangle size={13} className="mt-1 shrink-0 text-zinc-500" />
                              <span>
                                <span className="text-zinc-300">It is rarely precise.</span> This computer has
                                no GPS, so a fallback is town-level at best. The answer always says which
                                source produced it.
                              </span>
                            </li>
                          </ul>
                          <p className="mt-3 text-micro leading-5 text-zinc-600">
                            Declining costs nothing: the model is told there is no location and is told to
                            ask you rather than guess.
                          </p>
                        </>
                      ) : (
                        <p className="text-small leading-6 text-zinc-500">
                          Location is switched off on the server, so it cannot work out where you are. Every
                          other capability is unaffected.
                        </p>
                      )}
                    </Section>

                    <Section
                      title="Uploaded documents and web pages"
                      hint="The model reads whatever you attach and whatever it finds while searching, and text in either can try to instruct it. That is the main reason a command has to be shown to you before it runs."
                    >
                      <p className="text-small leading-6 text-zinc-500">
                        Whether a command runs on its own or asks you first is set in the Permissions tab,
                        the one you reached this panel from.
                      </p>
                    </Section>
                  </>
                )}

                {advancedSection === 'Data' && (
                  <>
                    <Section title="Documents" hint={`${documents.length} attached to this thread. Removing one deletes its stored chunks.`}>
                      {documents.length === 0 ? (
                        <p className="text-small text-zinc-600">Nothing here yet.</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {documents.map((document) => (
                            <li key={document.document_id} className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                              <span className="min-w-0 flex-1 truncate text-small-lg text-zinc-300">{document.filename}</span>
                              <span className="shrink-0 text-micro text-zinc-600">{document.chunks_stored} chunks</span>
                              <button
                                type="button"
                                onClick={() => removeDocument(document.document_id)}
                                aria-label={`Delete ${document.filename}`}
                                className="shrink-0 rounded-md p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-200"
                              >
                                <Trash2 size={13} />
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                      {documentError && <p className="mt-2 text-small text-amber-300/90">{documentError}</p>}
                    </Section>

                    <Section
                      title="Memories"
                      hint="Facts the model kept with remember. A memory enters a conversation only when the model asks for it with recall; nothing here loads on its own."
                    >
                      {memoryError && <p className="mb-2 text-small text-amber-300/90">{memoryError}</p>}
                      {memories === null ? (
                        <p className="text-small text-zinc-600">Loading…</p>
                      ) : memories.length === 0 ? (
                        <p className="text-small text-zinc-600">Nothing here yet.</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {memories.map((memory) => (
                            <li
                              key={memory.id}
                              className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
                            >
                              <span className="min-w-0 flex-1">
                                {memory.label && (
                                  <span className="mr-2 rounded border border-white/[0.1] px-1.5 py-0.5 text-micro text-zinc-500">
                                    {memory.label}
                                  </span>
                                )}
                                <span className="text-small-lg text-zinc-300">{memory.text}</span>
                                <span className="mt-0.5 block text-micro text-zinc-600">
                                  {memory.created_at.slice(0, 10)}
                                </span>
                              </span>
                              <button
                                type="button"
                                onClick={() => void removeMemory(memory.id)}
                                aria-label={`Delete memory: ${memory.text.slice(0, 40)}`}
                                className="shrink-0 rounded-md p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-200"
                              >
                                <Trash2 size={13} />
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </Section>

                    <Section
                      title="Threads"
                      hint={`${threadCount} thread${threadCount === 1 ? '' : 's'} in this workspace. Renaming updates the sidebar; deleting removes the thread and its messages from the server.`}
                    >
                      {threads.length === 0 ? (
                        <p className="text-small text-zinc-600">Nothing here yet.</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {threads.map((thread) => (
                            <ThreadRow
                              key={thread.id}
                              thread={thread}
                              onRename={onRenameThread}
                              onDelete={onDeleteThread}
                            />
                          ))}
                        </ul>
                      )}
                    </Section>

                    <Section title="This browser" hint="Appearance, contrast, text size, density, sidebar layout, ambient mode and the default model.">
                      <button
                        type="button"
                        onClick={() => {
                    resetPreferences()
                    setTopTab('Advanced')
                    setAdvancedSection('Appearance')
                  }}
                        className="h-9 rounded-lg border border-white/[0.09] px-3.5 text-small text-zinc-300 transition hover:bg-white/[0.05]"
                      >
                        Reset appearance and defaults
                      </button>
                    </Section>
                  </>
                )}

                {advancedSection === 'Appearance' && (
                  <>
                    <Section title="Background" hint="Monochrome by design. Surfaces shift, the palette does not.">
                      <div role="radiogroup" aria-label="Background" className="grid gap-2">
                        {APPEARANCES.map((option) => (
                          <Choice
                            key={option.value}
                            selected={prefs.appearance === option.value}
                            onSelect={() => setAppearance(option.value as Appearance)}
                            label={option.label}
                            note={option.note}
                            swatch={option.swatch}
                          />
                        ))}
                      </div>
                    </Section>

                    <Section title="Contrast" hint="Lifts the dim greys used for secondary text.">
                      <div role="radiogroup" aria-label="Contrast" className="grid gap-2 sm:grid-cols-2">
                        <Choice
                          selected={prefs.contrast === 'standard'}
                          onSelect={() => setContrast('standard' as Contrast)}
                          label="Standard"
                          note="Tuned for pure black; secondary text clears WCAG AA."
                        />
                        <Choice
                          selected={prefs.contrast === 'high'}
                          onSelect={() => setContrast('high' as Contrast)}
                          label="High"
                          note="Brighter dim text for dim rooms or low-quality panels."
                        />
                      </div>
                    </Section>

                    <Section title="Text size" hint="Rescales the whole type scale, from thread titles to body copy.">
                      <div role="radiogroup" aria-label="Text size" className="grid gap-2 sm:grid-cols-3">
                        {TEXT_SIZES.map((option) => (
                          <Choice
                            key={option.value}
                            selected={prefs.textSize === option.value}
                            onSelect={() => setTextSize(option.value as TextSize)}
                            label={option.label}
                            note={option.note}
                          />
                        ))}
                      </div>
                    </Section>

                    <Section title="Density" hint="Tightens or loosens every gap and inset in the interface.">
                      <div role="radiogroup" aria-label="Density" className="grid gap-2 sm:grid-cols-3">
                        {DENSITIES.map((option) => (
                          <Choice
                            key={option.value}
                            selected={prefs.density === option.value}
                            onSelect={() => setDensity(option.value as Density)}
                            label={option.label}
                            note={option.note}
                          />
                        ))}
                      </div>
                    </Section>

                    <Section title="Sidebar" hint="Folds the thread list away to icons, or shows it in full. Also toggleable with ⌘B / Ctrl+B.">
                      <div role="radiogroup" aria-label="Sidebar" className="grid gap-2 sm:grid-cols-2">
                        <Choice
                          selected={!prefs.sidebarCollapsed}
                          onSelect={() => setSidebarCollapsed(false)}
                          label="Expanded"
                          note="Thread titles, dates and the search field."
                        />
                        <Choice
                          selected={prefs.sidebarCollapsed}
                          onSelect={() => setSidebarCollapsed(true)}
                          label="Collapsed"
                          note="An icon rail. Hover a thread for its title."
                        />
                      </div>
                    </Section>

                    <Section title="Ambient effects" hint="The animated backdrop behind the conversation.">
                      <div role="radiogroup" aria-label="Ambient background intensity" className="grid gap-2">
                        {AMBIENT_OPTIONS.map((option) => (
                          <Choice
                            key={option.mode}
                            selected={ambientMode === option.mode}
                            onSelect={() => setAmbientMode(option.mode)}
                            label={option.label}
                            note={option.description}
                            icon={option.icon}
                          />
                        ))}
                      </div>
                    </Section>
                  </>
                )}

                {advancedSection === 'Model' && (
                  <Section
                    title="Default model"
                    hint="Used for new threads. An existing thread keeps the model it was started with."
                  >
                    <div className="space-y-2.5">
                      <select
                        value={prefs.defaultModel || ''}
                        onChange={(event) => setDefaultModel(event.target.value)}
                        className={selectClass}
                        aria-label="Default model"
                      >
                        <option value="" className="bg-black text-white">
                          Server default{serverDefaultModel ? ` (${serverDefaultModel})` : ''}
                        </option>
                        {models.map((model) => (
                          <option key={model.id} value={model.id} className="bg-black text-white">
                            {model.id}
                          </option>
                        ))}
                      </select>
                      <p className="text-small leading-[1.6] text-zinc-600">
                        {models.length} model{models.length === 1 ? '' : 's'} available on this server. Reasoning models can take
                        a couple of minutes before the first token.
                      </p>
                    </div>
                  </Section>
                )}

                {advancedSection === 'Audit log' && (
                  <Section
                    title="Audit log"
                    hint="Every tool call the permission system handled, newest first. Filter by category or by decision."
                  >
                    <div className="space-y-3">
                      <div className="flex flex-wrap gap-2">
                        <label className="flex items-center gap-2 text-micro text-zinc-500">
                          Category
                          <select
                            value={auditCategory}
                            onChange={(event) => setAuditCategory(event.target.value)}
                            className="h-7 rounded border border-white/[0.1] bg-black px-2 text-micro text-zinc-200 outline-none focus:border-white/30"
                          >
                            <option value="">All</option>
                            {autonomySettings?.categories && Object.entries(autonomySettings.categories).map(([cat, meta]) => (
                              <option key={cat} value={cat}>{(meta as { label: string }).label}</option>
                            ))}
                          </select>
                        </label>
                        <label className="flex items-center gap-2 text-micro text-zinc-500">
                          Decision
                          <select
                            value={auditDecision}
                            onChange={(event) => setAuditDecision(event.target.value)}
                            className="h-7 rounded border border-white/[0.1] bg-black px-2 text-micro text-zinc-200 outline-none focus:border-white/30"
                          >
                            <option value="">All</option>
                            <option value="auto_approved">Auto-approved</option>
                            <option value="user_approved">User-approved</option>
                            <option value="user_denied">User-denied</option>
                            <option value="blocked_never_allow">Blocked</option>
                          </select>
                        </label>
                      </div>
                      {auditLoading ? (
                        <p className="text-small text-zinc-600">Loading…</p>
                      ) : auditRows.length === 0 ? (
                        <p className="text-small text-zinc-600">Nothing logged yet.</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {auditRows.map((row) => (
                            <li key={row.id} className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                              <span className="min-w-0 flex-1">
                                <span className="text-small text-zinc-200">{row.tool_name}</span>
                                <span className="ml-2 rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-micro text-zinc-500">
                                  {row.decision}
                                </span>
                                <span className="ml-1.5 rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-micro text-zinc-500">
                                  {row.category}
                                </span>
                                <span className="mt-0.5 block text-micro leading-5 text-zinc-600">
                                  {row.arguments_summary ||
                                    (row.tool_name && `No details recorded.`)}
                                </span>
                                <span className="mt-1 block text-micro text-zinc-700">
                                  {new Date(row.timestamp).toLocaleString()}
                                </span>
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </Section>
                )}

                {advancedSection === 'About' && (
                  <>
                    <Section title="Pentagon">
                      <p className="text-small-lg leading-[1.7] text-zinc-500">
                        A personal AI workspace. FastAPI and LangGraph on the server, React and Vite in the
                        browser, models served by NVIDIA NIM. Your key, documents and threads stay on your own
                        machine and server.
                      </p>
                    </Section>

                    <Section title="Keyboard" hint="The composer keeps focus while you work.">
                      <dl className="grid gap-2 sm:grid-cols-2">
                        {SHORTCUTS.map(([keys, description]) => (
                          <div key={keys} className="flex items-center gap-2.5">
                            <dt className="shrink-0 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 font-mono text-micro text-zinc-400">
                              {keys}
                            </dt>
                            <dd className="min-w-0 truncate text-small text-zinc-600">{description}</dd>
                          </div>
                        ))}
                      </dl>
                    </Section>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}