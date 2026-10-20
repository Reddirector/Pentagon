import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Brain,
  Check,
  Cpu,
  ExternalLink,
  Eye,
  EyeOff,
  ImageIcon,
  KeyRound,
  Lock,
  Mail,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  User,
  UserCheck,
  UserPlus,
  X,
} from 'lucide-react'
import { apiRequest, setStoredNvidiaKey } from '../api'
import type { ModelInfo } from '../types'
import { LogomarkBadge } from './Logomark'
import { AmbientLayer } from './AmbientLayer'
import {
  AVATAR_THEMES,
  getPreferences,
  setUserAvatarColor,
  setUserEmail,
  setUserName,
} from '../lib/preferences'
import { getSupabase, isSupabaseConfigured } from '../lib/supabase'

export type FlowStep = 'key_input' | 'validating' | 'discovering' | 'model_select' | 'account_setup'

export interface KeyActivationFlowProps {
  userId?: string
  initialKey?: string
  onComplete: (data: {
    key: string
    models: ModelInfo[]
    selectedModel: string
    account?: {
      userName?: string
      userEmail?: string
      avatarColor?: string
    }
  }) => void
}

interface StoredAccount {
  email: string
  name: string
  passwordHash: string
  avatarColor: string
  createdAt: string
}

function getStoredAccounts(): StoredAccount[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem('pentagon.accounts_registry')
    return raw ? (JSON.parse(raw) as StoredAccount[]) : []
  } catch {
    return []
  }
}

function saveStoredAccount(account: StoredAccount): void {
  if (typeof window === 'undefined') return
  try {
    const accounts = getStoredAccounts().filter(
      (a) => a.email.toLowerCase() !== account.email.toLowerCase(),
    )
    accounts.push(account)
    localStorage.setItem('pentagon.accounts_registry', JSON.stringify(accounts))
  } catch {
    // Ignore storage quota errors
  }
}

async function hashPassword(password: string): Promise<string> {
  if (typeof window !== 'undefined' && window.crypto && window.crypto.subtle) {
    try {
      const msgBuffer = new TextEncoder().encode(password)
      const hashBuffer = await window.crypto.subtle.digest('SHA-256', msgBuffer)
      const hashArray = Array.from(new Uint8Array(hashBuffer))
      return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
    } catch {
      // fallback to btoa
    }
  }
  return btoa(password)
}

function cleanModelName(id: string): string {
  const parts = id.split('/')
  const base = parts[parts.length - 1] || id
  return base
    .replace(/-instruct/gi, ' Instruct')
    .replace(/-vision/gi, ' Vision')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

const FALLBACK_NVIDIA_MODELS: ModelInfo[] = [
  { id: 'meta/llama-3.2-11b-vision-instruct', supports_vision: true, context_window: 131072 },
  { id: 'nvidia/llama-3.1-nemotron-70b-instruct', supports_vision: false, context_window: 131072 },
  { id: 'meta/llama-3.2-90b-vision-instruct', supports_vision: true, context_window: 131072 },
  { id: 'mistralai/mistral-large-2-instruct', supports_vision: false, context_window: 131072 },
  { id: 'openai/gpt-oss-20b', supports_vision: false, context_window: 131072 },
  { id: 'mistralai/mistral-7b-instruct-v0.3', supports_vision: false, context_window: 32768 },
]

function getModelFamily(id: string): { label: string; tone: string } {
  const lower = id.toLowerCase()
  if (lower.includes('nemotron')) return { label: 'Nemotron', tone: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' }
  if (lower.includes('deepseek')) return { label: 'DeepSeek', tone: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20' }
  if (lower.includes('llama')) return { label: 'Llama', tone: 'text-blue-400 bg-blue-500/10 border-blue-500/20' }
  if (lower.includes('mistral') || lower.includes('mixtral')) return { label: 'Mistral', tone: 'text-amber-400 bg-amber-500/10 border-amber-500/20' }
  if (lower.includes('gpt') || lower.includes('openai')) return { label: 'OpenAI', tone: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' }
  if (lower.includes('gemma')) return { label: 'Gemma', tone: 'text-rose-400 bg-rose-500/10 border-rose-500/20' }
  if (lower.includes('qwen')) return { label: 'Qwen', tone: 'text-purple-400 bg-purple-500/10 border-purple-500/20' }
  return { label: 'NVIDIA', tone: 'text-zinc-400 bg-zinc-500/10 border-zinc-500/20' }
}

/**
 * Passive decorative star vectors and radiant sparkles for the AI vibe.
 */
function PassiveStarElements() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      {/* 4-point radiant compass stars */}
      <div className="absolute left-[8%] top-[14%] animate-pulse text-emerald-400/35 transition-all duration-1000" style={{ animationDuration: '4.5s' }}>
        <Sparkles size={18} />
      </div>
      <div className="absolute right-[12%] top-[18%] animate-pulse text-white/25 transition-all duration-1000" style={{ animationDuration: '6s', animationDelay: '1s' }}>
        <Star size={14} fill="currentColor" />
      </div>
      <div className="absolute left-[15%] bottom-[22%] animate-pulse text-teal-300/30 transition-all duration-1000" style={{ animationDuration: '5.2s', animationDelay: '2s' }}>
        <Sparkles size={16} />
      </div>
      <div className="absolute right-[16%] bottom-[26%] animate-pulse text-emerald-300/25 transition-all duration-1000" style={{ animationDuration: '7s', animationDelay: '1.5s' }}>
        <Star size={12} fill="currentColor" />
      </div>

      {/* Subtle starlight cross twinkles */}
      <div className="absolute left-[28%] top-[8%] size-1 rounded-full bg-emerald-300 shadow-[0_0_12px_#34d399] opacity-60" />
      <div className="absolute right-[32%] top-[10%] size-1.5 rounded-full bg-white shadow-[0_0_14px_rgba(255,255,255,0.8)] opacity-40" />
      <div className="absolute left-[22%] bottom-[12%] size-1 rounded-full bg-teal-200 shadow-[0_0_10px_#5eead4] opacity-50" />
      <div className="absolute right-[24%] bottom-[15%] size-1.5 rounded-full bg-emerald-400 shadow-[0_0_12px_#34d399] opacity-45" />

      {/* Deep concentric cosmic rings */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="size-[540px] rounded-full border border-emerald-500/[0.04]" />
        <div className="absolute size-[720px] rounded-full border border-white/[0.02]" />
        <div className="absolute size-[900px] rounded-full border border-white/[0.015]" />
      </div>
    </div>
  )
}

export function KeyActivationFlow({ userId, onComplete }: KeyActivationFlowProps) {
  const currentPrefs = getPreferences()
  const [step, setStep] = useState<FlowStep>('key_input')

  // BYOK: Always start keyInput empty so the user's private key is never pre-filled or exposed
  const [keyInput, setKeyInput] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState('')
  const [discoveredModels, setDiscoveredModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [modelSearch, setModelSearch] = useState('')

  // Step 3 Account states
  const [authMode, setAuthMode] = useState<'signup' | 'signin'>('signup')
  const [nameInput, setNameInput] = useState(currentPrefs.userName || '')
  const [emailInput, setEmailInput] = useState(currentPrefs.userEmail || '')
  const [passwordInput, setPasswordInput] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [avatarColor, setAvatarColor] = useState(currentPrefs.userAvatarColor || 'emerald')
  const [authBusy, setAuthBusy] = useState(false)
  const [authNotice, setAuthNotice] = useState('')

  // Live initials calculation: properly constrained to 2 letters
  const initials = useMemo(() => {
    const raw = (nameInput.trim() || 'Workspace User').split(' ').filter(Boolean)
    if (raw.length >= 2) return `${raw[0][0]}${raw[1][0]}`.toUpperCase()
    return (raw[0]?.slice(0, 2) || 'WU').toUpperCase()
  }, [nameInput])

  const avatarTheme = AVATAR_THEMES[avatarColor] ?? AVATAR_THEMES.emerald

  const filteredDiscoveredModels = useMemo(() => {
    const q = modelSearch.trim().toLowerCase()
    if (!q) return discoveredModels
    return discoveredModels.filter((model) => {
      const id = model.id.toLowerCase()
      const clean = cleanModelName(model.id).toLowerCase()
      const family = getModelFamily(model.id).label.toLowerCase()
      return id.includes(q) || clean.includes(q) || family.includes(q)
    })
  }, [discoveredModels, modelSearch])

  // Live key input validation check
  const trimmedKey = keyInput.trim()
  const isPrefixValid = trimmedKey.startsWith('nvapi-')
  const isKeyLengthValid = trimmedKey.length >= 16
  const isReadyToValidate = isPrefixValid && isKeyLengthValid

  // Handle key submission and validation
  async function handleValidate(event?: FormEvent) {
    if (event) event.preventDefault()
    if (!isReadyToValidate) {
      setError('Key must start with nvapi- and contain your full token string')
      return
    }

    setError('')
    setStep('validating')

    try {
      // 1. Validate key with backend / NVIDIA
      const validateResult = await apiRequest<{
        valid: boolean
        reason?: string
        models?: ModelInfo[]
        default_model?: string
      }>('/api/keys/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: trimmedKey }),
      })

      if (!validateResult.valid) {
        setError(validateResult.reason || 'Invalid NVIDIA API key. Please check your token.')
        setStep('key_input')
        return
      }

      // Store key in client session
      setStoredNvidiaKey(trimmedKey)
      try {
        await apiRequest('/api/keys', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, api_key: trimmedKey }),
        })
      } catch {
        // Safe if offline
      }

      // 2. Discover models associated with this key
      setStep('discovering')

      let models = validateResult.models || []
      let defModel = validateResult.default_model || ''

      if (!models.length) {
        try {
          const modelsResult = await apiRequest<{ models: ModelInfo[]; default_model?: string }>(
            '/api/models',
            { headers: { 'X-Nvidia-Key': trimmedKey } },
          )
          models = modelsResult.models || []
          defModel = modelsResult.default_model || ''
        } catch {
          // fallback
        }
      }
      if (!models.length) {
        models = FALLBACK_NVIDIA_MODELS
        defModel = FALLBACK_NVIDIA_MODELS[0].id
      }

      setDiscoveredModels(models)
      setSelectedModel(defModel || models[0].id)
      setStep('model_select')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not validate with NVIDIA endpoint')
      setStep('key_input')
    }
  }

  // Move from Step 2 (Model Select) to Step 3 (Account Setup)
  function handleModelSelected() {
    if (!selectedModel && discoveredModels.length > 0) {
      setSelectedModel(discoveredModels[0].id)
    }
    setError('')
    setStep('account_setup')
  }

  // Handle Account Setup Submission (Strict Verification)
  async function handleAccountSubmit(event?: FormEvent) {
    if (event) event.preventDefault()
    setAuthBusy(true)
    setError('')
    setAuthNotice('')

    const email = emailInput.trim().toLowerCase()
    const password = passwordInput.trim()

    // 1. Basic validation rules
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('Please provide a valid email address.')
      setAuthBusy(false)
      return
    }

    if (!password || password.length < 6) {
      setError('Password must contain at least 6 characters.')
      setAuthBusy(false)
      return
    }

    if (authMode === 'signup' && nameInput.trim().length < 2) {
      setError('Please enter your full name (at least 2 characters).')
      setAuthBusy(false)
      return
    }

    try {
      const client = getSupabase()
      const existingAccounts = getStoredAccounts()
      const existing = existingAccounts.find((a) => a.email.toLowerCase() === email)

      if (authMode === 'signin') {
        // ================= LOG IN MODE =================
        let authenticated = false
        let accountName = existing?.name || ''
        let accountColor = existing?.avatarColor || avatarColor

        if (client) {
          const { data, error: signInError } = await client.auth.signInWithPassword({
            email,
            password,
          })
          if (signInError) {
            setError(signInError.message || 'Invalid email or password.')
            setAuthBusy(false)
            return
          }
          if (data.session) {
            authenticated = true
            accountName = (data.session.user.user_metadata?.display_name as string) || existing?.name || nameInput.trim() || 'User'
          }
        }

        if (!authenticated) {
          if (!existing) {
            setError('Account not found. Please click "Create Account" to register first.')
            setAuthBusy(false)
            return
          }

          const hashed = await hashPassword(password)
          if (hashed !== existing.passwordHash) {
            setError('Incorrect password. Please verify your credentials and try again.')
            setAuthBusy(false)
            return
          }
          authenticated = true
          accountName = existing.name
          accountColor = existing.avatarColor
        }

        if (!authenticated) {
          setError('Could not verify credentials. Please try again.')
          setAuthBusy(false)
          return
        }

        // Successfully logged in
        setUserName(accountName)
        setUserEmail(email)
        setUserAvatarColor(accountColor)

        const finalModel = selectedModel || discoveredModels[0]?.id || 'nvidia/llama-3.1-nemotron-70b-instruct'
        localStorage.setItem('pentagon.defaultModel', finalModel)

        onComplete({
          key: trimmedKey,
          models: discoveredModels,
          selectedModel: finalModel,
          account: {
            userName: accountName,
            userEmail: email,
            avatarColor: accountColor,
          },
        })
      } else {
        // ================= CREATE ACCOUNT MODE =================
        if (existing) {
          setError('An account with this email address already exists. Please switch to "Log In".')
          setAuthBusy(false)
          return
        }

        const finalName = nameInput.trim()

        if (client) {
          const { error: signUpError } = await client.auth.signUp({
            email,
            password,
            options: { data: { display_name: finalName } },
          })
          if (signUpError && !signUpError.message.includes('already registered')) {
            setError(signUpError.message)
            setAuthBusy(false)
            return
          }
        }

        // Store new account record
        const passHash = await hashPassword(password)
        saveStoredAccount({
          email,
          name: finalName,
          passwordHash: passHash,
          avatarColor,
          createdAt: new Date().toISOString(),
        })

        setUserName(finalName)
        setUserEmail(email)
        setUserAvatarColor(avatarColor)

        const finalModel = selectedModel || discoveredModels[0]?.id || 'nvidia/llama-3.1-nemotron-70b-instruct'
        localStorage.setItem('pentagon.defaultModel', finalModel)

        onComplete({
          key: trimmedKey,
          models: discoveredModels,
          selectedModel: finalModel,
          account: {
            userName: finalName,
            userEmail: email,
            avatarColor,
          },
        })
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Authentication could not complete.')
    } finally {
      setAuthBusy(false)
    }
  }

  const isModelStep = step === 'model_select'
  const isAccountStep = step === 'account_setup'
  const isKeyStep = step === 'key_input' || step === 'validating' || step === 'discovering'

  return (
    <main className="relative flex min-h-dvh w-full items-center justify-center overflow-x-hidden overflow-y-auto bg-[#000000] px-3 sm:px-4 pt-[calc(1.25rem+env(safe-area-inset-top))] pb-[calc(1.75rem+env(safe-area-inset-bottom))] text-zinc-100 selection:bg-emerald-400/20">
      {/* Dynamic Ambient Constellation Layer */}
      <AmbientLayer />

      {/* Passive Celestial Star Elements for Authentic AI Vibe */}
      <PassiveStarElements />

      {/* Main Glassmorphic Onboarding Interface Card */}
      <section className="relative z-10 flex w-full max-w-[480px] flex-col items-center">
        {/* Sleek Central Pentagon SVG Brand Mark with Live Orbital Spin */}
        <div className="relative mb-4 sm:mb-5 flex items-center justify-center">
          <div className="absolute size-32 sm:size-36 rounded-full bg-emerald-400/[0.16] blur-3xl transition duration-700" />

          {(step === 'validating' || step === 'discovering' || authBusy) && (
            <div
              className="absolute size-28 sm:size-32 animate-spin rounded-full border border-dashed border-emerald-400/40"
              style={{ animationDuration: '3.6s' }}
            />
          )}

          <div className="relative flex size-20 sm:size-24 items-center justify-center rounded-2xl sm:rounded-3xl border border-white/[0.12] bg-[#090a0d]/90 shadow-[0_24px_60px_rgba(0,0,0,0.85)] backdrop-blur-2xl ring-1 ring-white/[0.06]">
            <div className="absolute inset-0 rounded-2xl sm:rounded-3xl bg-gradient-to-b from-white/[0.08] to-transparent" />
            <LogomarkBadge
              size={52}
              loading={step === 'validating' || step === 'discovering' || authBusy}
              className="transition duration-500 hover:scale-105"
            />
          </div>
        </div>

        {/* 3-Step High-Tech Progress Stepper */}
        <div className="mb-6 flex w-full max-w-[400px] items-center justify-between rounded-full border border-white/[0.08] bg-[#0b0c10]/85 p-1 backdrop-blur-2xl shadow-xl">
          {/* Step 1: API Key */}
          <button
            type="button"
            onClick={() => {
              if (discoveredModels.length > 0) setStep('key_input')
            }}
            disabled={step === 'validating' || step === 'discovering'}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-full py-1.5 text-micro font-medium transition ${
              isKeyStep
                ? 'border border-emerald-400/40 bg-emerald-400/15 text-emerald-300 shadow-[0_0_14px_rgba(52,211,153,0.25)]'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {discoveredModels.length > 0 ? (
              <Check size={12} className="text-emerald-400" />
            ) : (
              <span className={`size-1.5 rounded-full ${isKeyStep ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
            )}
            <span>01 API</span>
          </button>

          <span className="text-zinc-800">/</span>

          {/* Step 2: Model */}
          <button
            type="button"
            onClick={() => {
              if (discoveredModels.length > 0) setStep('model_select')
            }}
            disabled={discoveredModels.length === 0}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-full py-1.5 text-micro font-medium transition ${
              isModelStep
                ? 'border border-emerald-400/40 bg-emerald-400/15 text-emerald-300 shadow-[0_0_14px_rgba(52,211,153,0.25)]'
                : discoveredModels.length > 0
                ? 'text-zinc-400 hover:text-zinc-200'
                : 'cursor-not-allowed text-zinc-700'
            }`}
          >
            {isAccountStep ? (
              <Check size={12} className="text-emerald-400" />
            ) : (
              <span className={`size-1.5 rounded-full ${isModelStep ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
            )}
            <span>02 Model</span>
          </button>

          <span className="text-zinc-800">/</span>

          {/* Step 3: Account */}
          <button
            type="button"
            onClick={() => {
              if (discoveredModels.length > 0) setStep('account_setup')
            }}
            disabled={discoveredModels.length === 0}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-full py-1.5 text-micro font-medium transition ${
              isAccountStep
                ? 'border border-emerald-400/40 bg-emerald-400/15 text-emerald-300 shadow-[0_0_14px_rgba(52,211,153,0.25)]'
                : discoveredModels.length > 0
                ? 'text-zinc-400 hover:text-zinc-200'
                : 'cursor-not-allowed text-zinc-700'
            }`}
          >
            <span className={`size-1.5 rounded-full ${isAccountStep ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
            <span>03 Account</span>
          </button>
        </div>

        {/* Global Error Banner */}
        {error && (
          <div
            role="alert"
            className="mb-4 flex w-full items-center justify-between gap-2 rounded-xl border border-rose-500/25 bg-rose-500/[0.08] px-4 py-2.5 text-caption text-rose-300 backdrop-blur-md"
          >
            <span className="min-w-0 flex-1">{error}</span>
            <button
              type="button"
              onClick={() => setError('')}
              className="text-rose-400 hover:text-white"
              aria-label="Dismiss error"
            >
              <X size={13} />
            </button>
          </div>
        )}

        {/* Global Notice Banner */}
        {authNotice && (
          <div
            role="status"
            className="mb-4 flex w-full items-center justify-between gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/[0.08] px-4 py-2.5 text-caption text-emerald-300 backdrop-blur-md"
          >
            <span className="min-w-0 flex-1">{authNotice}</span>
            <button
              type="button"
              onClick={() => setAuthNotice('')}
              className="text-emerald-400 hover:text-white"
              aria-label="Dismiss notice"
            >
              <X size={13} />
            </button>
          </div>
        )}

        {/* =================================================================== */}
        {/* STEP 1: ENTER API KEY (STRICT BYOK - BRING YOUR OWN KEY)            */}
        {/* =================================================================== */}
        {step === 'key_input' && (
          <div className="flow-step-enter w-full text-center">
            <h1 className="text-hero font-semibold tracking-tight text-white">Connect AI Engine</h1>
            <p className="mt-1.5 text-small text-zinc-400">
              Bring Your Own Key (BYOK) — Enter your personal NVIDIA NIM key to connect enterprise inference models.
            </p>

            <form onSubmit={handleValidate} className="mt-5 w-full">
              <div className="group relative flex items-center rounded-2xl border border-white/[0.08] bg-white/[0.025] p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.5)] backdrop-blur-2xl transition-[border-color,box-shadow,background-color] duration-300 hover:border-white/[0.14] focus-within:border-emerald-400/40 focus-within:bg-[#080808] focus-within:shadow-[0_0_35px_rgba(16,185,129,0.14)]">
                <div className="flex pl-3.5 pr-2.5 text-zinc-500 transition-colors group-focus-within:text-emerald-400">
                  <KeyRound size={17} />
                </div>
                <input
                  id="nvidia-key-input"
                  type={showKey ? 'text' : 'password'}
                  autoComplete="off"
                  spellCheck={false}
                  value={keyInput}
                  onChange={(e) => {
                    setKeyInput(e.target.value)
                    setError('')
                  }}
                  placeholder="nvapi-••••••••••••••••"
                  className="h-10 w-full bg-transparent pr-2 font-mono text-small text-zinc-100 outline-none placeholder:text-zinc-600"
                  aria-label="NVIDIA API Key"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((prev) => !prev)}
                  aria-label={showKey ? 'Hide API key' : 'Show API key'}
                  title={showKey ? 'Hide API key' : 'Show API key'}
                  className="mr-1 flex size-8 shrink-0 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-white/[0.08] hover:text-zinc-200"
                >
                  {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
                <button
                  type="submit"
                  disabled={!isReadyToValidate}
                  aria-label="Validate & Discover Models"
                  title="Validate & Discover Models"
                  className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-400 text-black shadow-sm transition hover:bg-emerald-300 active:scale-95 disabled:cursor-not-allowed disabled:bg-white/[0.06] disabled:text-zinc-600"
                >
                  <ArrowRight size={16} />
                </button>
              </div>

              {/* Status Hint */}
              <div className="mt-3 flex items-center justify-between px-1 text-micro text-zinc-500">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`size-1.5 rounded-full ${
                      !trimmedKey ? 'bg-zinc-700' : isReadyToValidate ? 'bg-emerald-400' : 'bg-amber-400'
                    }`}
                  />
                  <span>
                    {!trimmedKey
                      ? 'Format starts with nvapi-'
                      : isReadyToValidate
                      ? 'Ready to connect'
                      : 'Incomplete token string'}
                  </span>
                </div>

                <a
                  href="https://build.nvidia.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-zinc-500 transition hover:text-emerald-400"
                >
                  <span>Get API key</span>
                  <ExternalLink size={10} />
                </a>
              </div>

              {/* Security Privacy Notice */}
              <div className="mt-6 flex items-center justify-center gap-2 text-caption-xs text-zinc-500">
                <ShieldCheck size={12} className="text-emerald-400/80" />
                <span>Dedicated private session · Never shared or exposed across users</span>
              </div>
            </form>
          </div>
        )}

        {/* =================================================================== */}
        {/* VALIDATING / DISCOVERING SPINNER STATES                            */}
        {/* =================================================================== */}
        {step === 'validating' && (
          <div className="flow-step-enter flex w-full flex-col items-center py-4 text-center">
            <h2 className="text-body font-semibold text-white">Validating Authorization</h2>
            <p className="mt-1 text-small text-zinc-400">Verifying credentials with NVIDIA NIM neural endpoints...</p>
            <div className="mt-5 h-1 w-48 overflow-hidden rounded-full bg-white/[0.08]">
              <div className="h-full w-2/3 animate-pulse rounded-full bg-gradient-to-r from-emerald-500 to-teal-400" />
            </div>
          </div>
        )}

        {step === 'discovering' && (
          <div className="flow-step-enter flex w-full flex-col items-center py-4 text-center">
            <h2 className="text-body font-semibold text-white">Discovering Neural Models</h2>
            <p className="mt-1 text-small text-zinc-400">Inspecting available chat, vision, and reasoning clusters...</p>

            <div className="mt-5 w-full space-y-2">
              <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 animate-pulse">
                <div className="flex items-center gap-2">
                  <span className="size-2 rounded-full bg-emerald-400/80" />
                  <div className="h-3.5 w-32 rounded bg-white/10" />
                </div>
                <div className="h-3 w-16 rounded bg-white/10" />
              </div>
              <div
                className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 animate-pulse"
                style={{ animationDelay: '150ms' }}
              >
                <div className="flex items-center gap-2">
                  <span className="size-2 rounded-full bg-cyan-400/80" />
                  <div className="h-3.5 w-28 rounded bg-white/10" />
                </div>
                <div className="h-3 w-14 rounded bg-white/10" />
              </div>
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* STEP 2: SELECT DEFAULT MODEL                                       */}
        {/* =================================================================== */}
        {step === 'model_select' && (
          <div className="flow-step-enter w-full text-center">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-caption text-emerald-300">
              <ShieldCheck size={14} className="text-emerald-400" />
              <span>{discoveredModels.length} Models Verified</span>
            </div>

            <h1 className="mt-2 text-hero font-semibold text-white">Select Default Model</h1>
            <p className="mt-1 text-small text-zinc-400">
              Choose your primary model. You can switch between any of them anytime in chat.
            </p>

            {/* Search Input for Models */}
            <div className="relative mt-3.5 w-full">
              <Search size={14} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input
                type="text"
                value={modelSearch}
                onChange={(e) => setModelSearch(e.target.value)}
                placeholder="Search models (nemotron, vision, deepseek, 70b)..."
                className="h-10 w-full rounded-xl border border-white/[0.08] bg-white/[0.03] pl-9 pr-8 text-small text-zinc-100 placeholder:text-zinc-500 transition focus:border-emerald-500/50 focus:bg-white/[0.05] focus:outline-none focus:ring-1 focus:ring-emerald-500/30"
              />
              {modelSearch && (
                <button
                  type="button"
                  onClick={() => setModelSearch('')}
                  aria-label="Clear search"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md p-1 text-zinc-400 hover:bg-white/10 hover:text-white"
                >
                  <X size={13} />
                </button>
              )}
            </div>

            <div className="mt-2 flex items-center justify-between px-1 text-micro text-zinc-500">
              <span>{filteredDiscoveredModels.length} of {discoveredModels.length} models ready</span>
              {modelSearch && (
                <button
                  type="button"
                  onClick={() => setModelSearch('')}
                  className="text-emerald-400 hover:underline"
                >
                  Clear filter
                </button>
              )}
            </div>

            {/* Model Cards List */}
            <div className="mt-2.5 max-h-[240px] w-full space-y-2 overflow-y-auto pr-1 text-left custom-scrollbar">
              {filteredDiscoveredModels.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <Cpu size={24} className="mb-2 text-zinc-600" />
                  <p className="text-small text-zinc-400">No models match &ldquo;{modelSearch}&rdquo;</p>
                  <button
                    type="button"
                    onClick={() => setModelSearch('')}
                    className="mt-2 text-caption text-emerald-400 hover:underline"
                  >
                    Clear search filter
                  </button>
                </div>
              ) : (
                filteredDiscoveredModels.map((model) => {
                  const isSelected = model.id === selectedModel
                  const family = getModelFamily(model.id)
                  const isReasoning = model.is_reasoning || model.id.includes('r1')
                  const isVision = model.supports_vision || model.id.includes('vision')

                  return (
                    <button
                      key={model.id}
                      type="button"
                      onClick={() => setSelectedModel(model.id)}
                      className={`group flex w-full items-center justify-between rounded-2xl border p-3 text-left transition-all duration-200 active:scale-[0.99] ${
                        isSelected
                          ? 'border-emerald-500/50 bg-emerald-500/[0.08] shadow-[0_0_20px_rgba(16,185,129,0.15)] ring-1 ring-emerald-500/30'
                          : 'border-white/[0.08] bg-white/[0.02] hover:border-white/[0.18] hover:bg-white/[0.045] hover:translate-x-0.5'
                      }`}
                    >
                      <div className="min-w-0 flex-1 pr-2">
                        <div className="flex items-center gap-2">
                          <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${family.tone}`}>
                            {family.label}
                          </span>
                          <span className="truncate text-small font-medium text-zinc-100">
                            {cleanModelName(model.id)}
                          </span>
                        </div>

                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-micro text-zinc-500">
                          {isVision && (
                            <span className="flex items-center gap-1 rounded bg-white/[0.04] px-1.5 py-0.5 text-zinc-300">
                              <ImageIcon size={10} className="text-emerald-400" />
                              <span>Vision</span>
                            </span>
                          )}
                          {isReasoning && (
                            <span className="flex items-center gap-1 rounded bg-white/[0.04] px-1.5 py-0.5 text-cyan-300">
                              <Brain size={10} className="text-cyan-400" />
                              <span>Reasoning</span>
                            </span>
                          )}
                          <span className="rounded bg-white/[0.04] px-1.5 py-0.5 text-zinc-400">
                            128K ctx
                          </span>
                        </div>
                      </div>

                      <div
                        className={`grid size-6 shrink-0 place-items-center rounded-full border transition-all duration-200 ${
                          isSelected
                            ? 'border-emerald-400 bg-emerald-400 text-black badge-pop shadow-[0_0_10px_rgba(52,211,153,0.5)]'
                            : 'border-white/[0.15] bg-transparent text-transparent group-hover:border-white/[0.3]'
                        }`}
                      >
                        <Check size={13} strokeWidth={2.8} />
                      </div>
                    </button>
                  )
                })
              )}
            </div>

            {/* Actions: Next to Account Setup or Back to Key */}
            <div className="mt-5 flex flex-col items-center gap-2.5">
              <button
                type="button"
                onClick={handleModelSelected}
                className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 font-medium text-black shadow-[0_0_24px_rgba(52,211,153,0.3)] transition-all duration-200 hover:bg-emerald-300 hover:shadow-[0_0_30px_rgba(52,211,153,0.5)] active:scale-95"
              >
                <span>Continue to Account Setup</span>
                <ArrowRight size={16} />
              </button>

              <button
                type="button"
                onClick={() => setStep('key_input')}
                className="flex items-center gap-1 text-micro text-zinc-500 transition hover:text-zinc-300"
              >
                <ArrowLeft size={12} />
                <span>Change API key</span>
              </button>
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* STEP 3: ACCOUNT & PROFILE SETUP (AUTHENTICATED SIGN IN / SIGN UP)   */}
        {/* =================================================================== */}
        {step === 'account_setup' && (
          <div className="flow-step-enter w-full text-center">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-caption text-emerald-300">
              <Sparkles size={13} className="text-emerald-400" />
              <span>Step 3 · Identity &amp; Security</span>
            </div>

            <h1 className="mt-2 text-hero font-semibold text-white">
              {authMode === 'signup' ? 'Create Your Account' : 'Sign In to Your Account'}
            </h1>
            <p className="mt-1 text-small text-zinc-400">
              {authMode === 'signup'
                ? 'Register your profile to secure your workspace, conversations, and document exports.'
                : 'Enter your credentials to access your existing workspace and saved history.'}
            </p>

            {/* Mode Switch Tabs */}
            <div className="mt-4 flex w-full rounded-xl border border-white/[0.08] bg-white/[0.025] p-1">
              <button
                type="button"
                onClick={() => {
                  setAuthMode('signup')
                  setError('')
                }}
                className={`flex-1 rounded-lg py-1.5 text-small font-medium transition ${
                  authMode === 'signup'
                    ? 'bg-white/[0.1] text-white shadow-sm'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                Create Account
              </button>
              <button
                type="button"
                onClick={() => {
                  setAuthMode('signin')
                  setError('')
                }}
                className={`flex-1 rounded-lg py-1.5 text-small font-medium transition ${
                  authMode === 'signin'
                    ? 'bg-white/[0.1] text-white shadow-sm'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                Sign In
              </button>
            </div>

            {/* Profile Avatar Preview Card */}
            <div className="mt-4 flex items-center gap-3.5 rounded-2xl border border-white/[0.08] bg-[#0c0d12]/90 p-3 text-left shadow-md">
              <div
                className={`grid size-12 shrink-0 place-items-center rounded-2xl border font-bold text-base transition-all duration-300 select-none ${avatarTheme.bg} ${avatarTheme.text} ${avatarTheme.border}`}
              >
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-small font-semibold text-white">
                  {nameInput.trim() || (authMode === 'signin' ? 'Account Login' : 'New User')}
                </div>
                <div className="truncate text-micro text-zinc-400">
                  {emailInput.trim() || 'email@example.com'}
                </div>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-1.5 text-[11px]">
                  <div className="flex items-center gap-1.5 text-emerald-400/90">
                    <span className="size-1.5 rounded-full bg-emerald-400" />
                    <span>Model: {cleanModelName(selectedModel || 'Nemotron 70B')}</span>
                  </div>
                  <div className="flex items-center gap-1 text-zinc-500">
                    <span className={`size-1.5 rounded-full ${isSupabaseConfigured ? 'bg-emerald-400' : 'bg-teal-400'}`} />
                    <span>{isSupabaseConfigured ? 'Cloud Sync' : 'Active'}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Form Fields */}
            <form onSubmit={handleAccountSubmit} className="mt-4 space-y-3 text-left">
              {/* Display Name (Only in Sign Up mode) */}
              {authMode === 'signup' && (
                <div>
                  <label className="mb-1 block text-micro font-medium text-zinc-400" htmlFor="setup-name">
                    Full Name
                  </label>
                  <div className="relative flex items-center rounded-xl border border-white/[0.08] bg-white/[0.03] transition focus-within:border-emerald-400/40 focus-within:bg-white/[0.05]">
                    <User size={15} className="ml-3 text-zinc-500" />
                    <input
                      id="setup-name"
                      type="text"
                      required
                      value={nameInput}
                      onChange={(e) => setNameInput(e.target.value)}
                      placeholder="e.g. Alex Mercer"
                      className="h-10 w-full bg-transparent px-3 text-small text-zinc-100 outline-none placeholder:text-zinc-600"
                    />
                  </div>
                </div>
              )}

              {/* Email Address */}
              <div>
                <label className="mb-1 block text-micro font-medium text-zinc-400" htmlFor="setup-email">
                  Email Address
                </label>
                <div className="relative flex items-center rounded-xl border border-white/[0.08] bg-white/[0.03] transition focus-within:border-emerald-400/40 focus-within:bg-white/[0.05]">
                  <Mail size={15} className="ml-3 text-zinc-500" />
                  <input
                    id="setup-email"
                    type="email"
                    required
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    placeholder="alex@domain.com"
                    className="h-10 w-full bg-transparent px-3 text-small text-zinc-100 outline-none placeholder:text-zinc-600"
                  />
                </div>
              </div>

              {/* Password */}
              <div>
                <label className="mb-1 block text-micro font-medium text-zinc-400" htmlFor="setup-password">
                  Password
                </label>
                <div className="relative flex items-center rounded-xl border border-white/[0.08] bg-white/[0.03] transition focus-within:border-emerald-400/40 focus-within:bg-white/[0.05]">
                  <Lock size={15} className="ml-3 text-zinc-500" />
                  <input
                    id="setup-password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    value={passwordInput}
                    onChange={(e) => setPasswordInput(e.target.value)}
                    placeholder={authMode === 'signup' ? 'Min 6 characters' : 'Enter account password'}
                    className="h-10 w-full bg-transparent px-3 text-small text-zinc-100 outline-none placeholder:text-zinc-600"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((p) => !p)}
                    className="mr-2.5 text-zinc-500 hover:text-zinc-300"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </div>

              {/* Avatar Accent Palette (Only in Sign Up mode) */}
              {authMode === 'signup' && (
                <div>
                  <span className="mb-1.5 block text-micro font-medium text-zinc-400">
                    Avatar Accent Tone
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(AVATAR_THEMES).map(([colorKey, theme]) => {
                      const isSelected = avatarColor === colorKey
                      return (
                        <button
                          key={colorKey}
                          type="button"
                          onClick={() => setAvatarColor(colorKey)}
                          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-micro capitalize transition ${
                            isSelected
                              ? 'border-emerald-400 bg-white/[0.08] text-white ring-1 ring-emerald-400/50'
                              : 'border-white/[0.08] bg-white/[0.02] text-zinc-400 hover:border-white/[0.18]'
                          }`}
                        >
                          <span className={`size-2 rounded-full ${theme.bg} ${theme.border}`} />
                          <span>{colorKey}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Main Submit Button */}
              <div className="pt-2">
                <button
                  type="submit"
                  disabled={authBusy}
                  className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 font-medium text-black shadow-[0_0_24px_rgba(52,211,153,0.3)] transition hover:bg-emerald-300 active:scale-95 disabled:opacity-50"
                >
                  {authBusy ? (
                    <span className="inline-block size-4 animate-spin rounded-full border-2 border-black border-t-transparent" />
                  ) : authMode === 'signup' ? (
                    <UserPlus size={16} />
                  ) : (
                    <UserCheck size={16} />
                  )}
                  <span>
                    {authBusy
                      ? 'Authenticating...'
                      : authMode === 'signup'
                      ? 'Create Account & Enter Workspace'
                      : 'Sign In & Enter Workspace'}
                  </span>
                  <ArrowRight size={16} />
                </button>
              </div>

              {/* Back to Model Selection */}
              <div className="text-center pt-2">
                <button
                  type="button"
                  onClick={() => setStep('model_select')}
                  className="inline-flex items-center gap-1 text-micro text-zinc-500 transition hover:text-zinc-300"
                >
                  <ArrowLeft size={12} />
                  <span>Back to model selection</span>
                </button>
              </div>
            </form>
          </div>
        )}
      </section>
    </main>
  )
}
