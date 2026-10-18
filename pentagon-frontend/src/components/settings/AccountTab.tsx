/**
 * The Account top tab: local workspace identity, backend address, NVIDIA key
 * and the optional Supabase sign-in. State and handlers moved here verbatim
 * from SettingsDialog.tsx; nothing behavioural changed.
 */
import { useEffect, useState, useSyncExternalStore } from 'react'
import { AlertTriangle, Check, Copy, Eye, EyeOff } from 'lucide-react'
import {
  getPreferences,
  setUserAvatarColor,
  setUserEmail,
  setUserName,
  setWorkspaceName,
  subscribePreferences,
  AVATAR_THEMES,
} from '../../lib/preferences'
import { apiRequest, getApiBase, getCapability, setApiBase } from '../../api'
import { getSupabase, isSupabaseConfigured } from '../../lib/supabase'
import { Section, inputClass } from './shared'

export function AccountTab({ userId, onKeySaved }: { userId: string; onKeySaved: () => void }) {
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  const [copied, setCopied] = useState(false)
  const [apiBaseDraft, setApiBaseDraft] = useState(() => getApiBase())
  const [testingApi, setTestingApi] = useState(false)
  const [apiBaseTest, setApiBaseTest] = useState<{ ok: boolean; message: string } | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [keyState, setKeyState] = useState<'idle' | 'checking' | 'valid' | 'invalid'>('idle')
  const [keyMessage, setKeyMessage] = useState('')
  const [savingKey, setSavingKey] = useState(false)
  const [showNvidiaKey, setShowNvidiaKey] = useState(false)
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
      const capability = await getCapability()
      const headers: Record<string, string> = {}
      if (capability) headers['X-Pentagon-Capability'] = capability
      const response = await fetch(`${candidate}/api/models?user_id=${encodeURIComponent(userId)}`, { headers })
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
      const trimmed = keyInput.trim()
      localStorage.setItem('pentagon.nvidiaKey', trimmed)
      await apiRequest('/api/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, api_key: trimmed }),
      })
      setKeyState('idle')
      setKeyMessage('Saved. Ready and active for model queries.')
      onKeySaved()
    } catch (cause) {
      setKeyMessage(cause instanceof Error ? cause.message : 'Could not store the key.')
    } finally {
      setSavingKey(false)
    }
  }

  function clearKey() {
    localStorage.removeItem('pentagon.nvidiaKey')
    setKeyInput('')
    setKeyState('idle')
    setKeyMessage('Key removed from this browser.')
    onKeySaved()
  }

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

  const userName = prefs.userName || 'User'
  const userEmail = prefs.userEmail || 'user@pentagon.local'
  const avatarTheme = AVATAR_THEMES[prefs.userAvatarColor] ?? AVATAR_THEMES.emerald
  const initials =
    userName
      .split(' ')
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0].toUpperCase())
      .join('') || 'A'

  return (
    <>
      <Section
        title="Profile & Identity"
        hint="Your personal avatar and name used across chat threads, shared documents, and export deliverables."
      >
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <div
              className={`grid size-14 shrink-0 place-items-center rounded-2xl border ${avatarTheme.border} ${avatarTheme.bg} font-semibold text-hero-fluid ${avatarTheme.text} shadow-inner`}
            >
              {initials}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-body font-semibold text-zinc-100">{userName}</div>
              <div className="text-small text-zinc-400">{userEmail}</div>
              <div className="mt-1 flex items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-md border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-caption-xs font-medium text-emerald-300">
                  <span className="size-1.5 rounded-full bg-emerald-400" /> Active Session
                </span>
                <span className="text-caption-xs text-zinc-500">Local &amp; Secure</span>
              </div>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-micro-sm text-zinc-400">Display name</span>
              <input
                type="text"
                value={prefs.userName}
                onChange={(e) => setUserName(e.target.value)}
                placeholder="Your name"
                className={inputClass}
                aria-label="Display name"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-micro-sm text-zinc-400">Email address</span>
              <input
                type="email"
                value={prefs.userEmail}
                onChange={(e) => setUserEmail(e.target.value)}
                placeholder="user@example.com"
                className={inputClass}
                aria-label="Email address"
              />
            </label>
          </div>

          <div>
            <span className="mb-2 block text-micro-sm text-zinc-400">Avatar accent theme</span>
            <div className="flex flex-wrap gap-2.5">
              {Object.entries(AVATAR_THEMES).map(([colorKey, theme]) => {
                const isSelected = (prefs.userAvatarColor || 'emerald') === colorKey
                return (
                  <button
                    key={colorKey}
                    type="button"
                    onClick={() => setUserAvatarColor(colorKey)}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-caption font-medium transition ${
                      isSelected
                        ? `${theme.border} ${theme.bg} ${theme.text} ring-1 ${theme.ring}`
                        : 'border-white/[0.08] bg-white/[0.02] text-zinc-400 hover:border-white/[0.16] hover:text-zinc-200'
                    }`}
                  >
                    <span className={`size-3 rounded-full border ${theme.border} ${theme.bg}`} />
                    <span className="capitalize">{colorKey}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </Section>

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
          <div className="relative flex items-center">
            <input
              type={showNvidiaKey ? 'text' : 'password'}
              value={keyInput}
              onChange={(event) => {
                setKeyInput(event.target.value)
                setKeyState('idle')
                setKeyMessage('')
              }}
              placeholder="nvapi-…"
              autoComplete="off"
              spellCheck={false}
              className={`${inputClass} pr-10 font-mono`}
              aria-label="NVIDIA API key"
            />
            <button
              type="button"
              onClick={() => setShowNvidiaKey((prev) => !prev)}
              aria-label={showNvidiaKey ? 'Hide API key' : 'Show API key'}
              title={showNvidiaKey ? 'Hide API key' : 'Show API key'}
              className="absolute right-2 flex size-7 items-center justify-center rounded-md text-zinc-500 transition hover:bg-white/[0.08] hover:text-zinc-200"
            >
              {showNvidiaKey ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
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
            {typeof window !== 'undefined' && localStorage.getItem('pentagon.nvidiaKey') ? (
              <button
                type="button"
                onClick={clearKey}
                className="h-9 rounded-lg border border-rose-500/30 px-3 text-small text-rose-300 transition hover:bg-rose-500/10"
              >
                Clear key
              </button>
            ) : null}
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
  )
}
