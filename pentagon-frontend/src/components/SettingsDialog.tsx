import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { AlertTriangle, Check, Copy, MoonStar, Sun, Trash2, Waves, X } from 'lucide-react'
import { getAmbientMode, setAmbientMode, subscribeAmbient } from '../lib/ambient'
import type { AmbientMode } from '../lib/ambient'
import {
  APPEARANCES,
  getPreferences,
  resetPreferences,
  setAppearance,
  setContrast,
  setDefaultModel,
  setWorkspaceName,
  subscribePreferences,
} from '../lib/preferences'
import type { Appearance, Contrast } from '../lib/preferences'
import { getSupabase, isSupabaseConfigured } from '../lib/supabase'
import { apiRequest } from '../api'
import type { DocumentInfo, ModelInfo } from '../types'

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

const TABS = ['Account', 'Appearance', 'Model', 'Data', 'About'] as const
type Tab = (typeof TABS)[number]

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-white/[0.06] px-6 py-5 last:border-b-0">
      <h3 className="text-[10px] font-medium uppercase tracking-[.16em] text-zinc-500">{title}</h3>
      {hint && <p className="mt-1.5 text-[11px] leading-5 text-zinc-600">{hint}</p>}
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
        <span className="block text-[12px] font-medium text-zinc-100">{label}</span>
        <span className="mt-0.5 block text-[10.5px] leading-[1.55] text-zinc-600">{note}</span>
      </span>
      {selected && <Check size={14} className="ml-auto mt-0.5 shrink-0 text-zinc-100" />}
    </button>
  )
}

const inputClass =
  'h-9 w-full rounded-lg border border-white/[0.09] bg-white/[0.03] px-3 text-[12px] text-zinc-100 outline-none transition placeholder:text-zinc-700 focus:border-white/30'

// Kept separate from inputClass on purpose: adding bg-black/text-white on top of
// the input utilities would lose to them in the generated stylesheet, where
// source order decides, not the order written in the attribute.
const selectClass =
  'h-9 w-full cursor-pointer rounded-lg border border-white/[0.12] bg-black px-3 text-[12px] text-white outline-none transition focus:border-white/30'

export function SettingsDialog({
  userId,
  models,
  serverDefaultModel,
  documents,
  threadCount,
  onClose,
  onKeySaved,
  onDocumentDeleted,
}: {
  userId: string
  models: ModelInfo[]
  serverDefaultModel: string
  documents: DocumentInfo[]
  threadCount: number
  onClose: () => void
  onKeySaved: () => void
  onDocumentDeleted: (documentId: string) => void
}) {
  const [tab, setTab] = useState<Tab>('Account')
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
    try {
      await apiRequest(`/api/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' })
      onDocumentDeleted(documentId)
    } catch {
      /* The list is left untouched; the next refresh will show the truth. */
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[8vh] pb-[4vh] backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        className="panel-enter flex max-h-full w-full max-w-[720px] flex-col overflow-hidden rounded-2xl border border-white/[0.1] bg-[var(--surface-panel)] shadow-[0_40px_120px_rgba(0,0,0,.6)] outline-none"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/[0.07] px-6 py-4">
          <h2 className="text-[13px] font-semibold tracking-[-.01em] text-zinc-100">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-lg p-1 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <X size={15} />
          </button>
        </div>

        <div role="tablist" aria-label="Settings sections" className="flex gap-1 overflow-x-auto border-b border-white/[0.07] px-4">
          {TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              onClick={() => setTab(name)}
              className={`relative shrink-0 px-3 py-2.5 text-[11.5px] font-medium transition ${
                tab === name ? 'text-zinc-100' : 'text-zinc-600 hover:text-zinc-300'
              }`}
            >
              {name}
              {tab === name && <span className="absolute inset-x-2 -bottom-px h-px bg-white" />}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'Account' && (
            <>
              <Section title="Workspace" hint="Threads and documents are scoped to this id. It is generated in this browser and sent with every request.">
                <div className="space-y-3">
                  <label className="block">
                    <span className="mb-1.5 block text-[10.5px] text-zinc-500">Name</span>
                    <input
                      value={prefs.workspaceName}
                      onChange={(event) => setWorkspaceName(event.target.value)}
                      maxLength={40}
                      className={inputClass}
                      aria-label="Workspace name"
                    />
                  </label>
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] text-zinc-500">
                      {userId}
                    </code>
                    <button
                      type="button"
                      onClick={copyId}
                      className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.09] px-3 text-[11px] text-zinc-400 transition hover:bg-white/[0.05] hover:text-zinc-200"
                    >
                      {copied ? <Check size={13} /> : <Copy size={13} />}
                      {copied ? 'Copied' : 'Copy'}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={newWorkspace}
                    className="flex items-center gap-1.5 text-[11px] text-zinc-600 transition hover:text-zinc-300"
                  >
                    <AlertTriangle size={12} /> Start a new workspace
                  </button>
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
                      className="h-9 rounded-lg border border-white/[0.09] px-3.5 text-[11px] text-zinc-300 transition hover:bg-white/[0.05] disabled:opacity-40"
                    >
                      {keyState === 'checking' ? 'Checking…' : 'Validate'}
                    </button>
                    <button
                      type="button"
                      onClick={saveKey}
                      disabled={keyState !== 'valid' || savingKey}
                      className="h-9 rounded-lg bg-white px-3.5 text-[11px] font-medium text-black transition hover:bg-zinc-200 disabled:opacity-40"
                    >
                      {savingKey ? 'Saving…' : 'Save key'}
                    </button>
                    {keyMessage && (
                      <span className={`text-[11px] ${keyState === 'invalid' ? 'text-zinc-400' : 'text-zinc-500'}`}>
                        {keyMessage}
                      </span>
                    )}
                  </div>
                </div>
              </Section>

              <Section
                title="Cloud account"
                hint="Optional. Signing in keeps threads on a Supabase project instead of this browser's workspace id."
              >
                {!isSupabaseConfigured ? (
                  <p className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-3 text-[11px] leading-[1.6] text-zinc-600">
                    Not configured. Set <code className="text-zinc-400">VITE_SUPABASE_URL</code> and{' '}
                    <code className="text-zinc-400">VITE_SUPABASE_ANON_KEY</code> in{' '}
                    <code className="text-zinc-400">pentagon-frontend/.env</code>, apply{' '}
                    <code className="text-zinc-400">supabase/schema.sql</code>, then restart the dev server. Everything
                    else on this page works without it.
                  </p>
                ) : sessionEmail ? (
                  <div className="flex items-center gap-3">
                    <span className="min-w-0 flex-1 truncate text-[12px] text-zinc-200">{sessionEmail}</span>
                    <button
                      type="button"
                      onClick={signOut}
                      disabled={authBusy}
                      className="h-9 shrink-0 rounded-lg border border-white/[0.09] px-3.5 text-[11px] text-zinc-300 transition hover:bg-white/[0.05] disabled:opacity-40"
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
                        className="h-9 rounded-lg bg-white px-3.5 text-[11px] font-medium text-black transition hover:bg-zinc-200 disabled:opacity-40"
                      >
                        {authBusy ? 'Working…' : authMode === 'signin' ? 'Sign in' : 'Create account'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setAuthMode(authMode === 'signin' ? 'signup' : 'signin')
                          setAuthMessage('')
                        }}
                        className="text-[11px] text-zinc-600 transition hover:text-zinc-300"
                      >
                        {authMode === 'signin' ? 'Need an account?' : 'Already registered?'}
                      </button>
                      {authMessage && <span className="text-[11px] text-zinc-500">{authMessage}</span>}
                    </div>
                  </form>
                )}
              </Section>
            </>
          )}

          {tab === 'Appearance' && (
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

          {tab === 'Model' && (
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
                <p className="text-[11px] leading-[1.6] text-zinc-600">
                  {models.length} model{models.length === 1 ? '' : 's'} available on this server. Reasoning models can take
                  a couple of minutes before the first token.
                </p>
              </div>
            </Section>
          )}

          {tab === 'Data' && (
            <>
              <Section title="Documents" hint={`${documents.length} attached to this thread. Removing one deletes its stored chunks.`}>
                {documents.length === 0 ? (
                  <p className="text-[11px] text-zinc-600">Nothing attached.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {documents.map((document) => (
                      <li key={document.document_id} className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                        <span className="min-w-0 flex-1 truncate text-[11.5px] text-zinc-300">{document.filename}</span>
                        <span className="shrink-0 text-[10px] text-zinc-600">{document.chunks_stored} chunks</span>
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
              </Section>

              <Section title="This browser" hint={`${threadCount} thread${threadCount === 1 ? '' : 's'} in this workspace.`}>
                <button
                  type="button"
                  onClick={() => {
                    resetPreferences()
                    setTab('Appearance')
                  }}
                  className="h-9 rounded-lg border border-white/[0.09] px-3.5 text-[11px] text-zinc-300 transition hover:bg-white/[0.05]"
                >
                  Reset appearance and defaults
                </button>
              </Section>
            </>
          )}

          {tab === 'About' && (
            <>
              <Section title="Pentagon">
                <p className="text-[11.5px] leading-[1.7] text-zinc-500">
                  A personal AI workspace. FastAPI and LangGraph on the server, React and Vite in the browser, models
                  served by NVIDIA NIM. Your key, documents and threads stay on your own machine and server.
                </p>
              </Section>

              <Section title="Keyboard" hint="The composer keeps focus while you work.">
                <dl className="grid gap-2 sm:grid-cols-2">
                  {SHORTCUTS.map(([keys, description]) => (
                    <div key={keys} className="flex items-center gap-2.5">
                      <dt className="shrink-0 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">
                        {keys}
                      </dt>
                      <dd className="min-w-0 truncate text-[11px] text-zinc-600">{description}</dd>
                    </div>
                  ))}
                </dl>
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}