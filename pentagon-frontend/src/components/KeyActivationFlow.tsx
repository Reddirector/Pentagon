import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowRight,
  Brain,
  Check,
  Cpu,
  ExternalLink,
  Eye,
  EyeOff,
  ImageIcon,
  KeyRound,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { apiRequest } from '../api'
import type { ModelInfo } from '../types'
import { LogomarkBadge } from './Logomark'

export type FlowStep = 'key_input' | 'validating' | 'discovering' | 'models_ready'

export interface KeyActivationFlowProps {
  userId?: string
  initialKey?: string
  onComplete: (data: { key: string; models: ModelInfo[]; selectedModel: string }) => void
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

function getModelFamily(id: string): { label: string; tone: string } {
  const lower = id.toLowerCase()
  if (lower.includes('nemotron')) return { label: 'Nemotron', tone: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' }
  if (lower.includes('deepseek')) return { label: 'DeepSeek', tone: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20' }
  if (lower.includes('llama')) return { label: 'Llama', tone: 'text-blue-400 bg-blue-500/10 border-blue-500/20' }
  if (lower.includes('mistral')) return { label: 'Mistral', tone: 'text-amber-400 bg-amber-500/10 border-amber-500/20' }
  if (lower.includes('gemma')) return { label: 'Gemma', tone: 'text-rose-400 bg-rose-500/10 border-rose-500/20' }
  if (lower.includes('qwen')) return { label: 'Qwen', tone: 'text-purple-400 bg-purple-500/10 border-purple-500/20' }
  return { label: 'NVIDIA', tone: 'text-zinc-400 bg-zinc-500/10 border-zinc-500/20' }
}

export function KeyActivationFlow({ userId, initialKey = '', onComplete }: KeyActivationFlowProps) {
  const [step, setStep] = useState<FlowStep>('key_input')
  const [keyInput, setKeyInput] = useState(initialKey)
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState('')
  const [discoveredModels, setDiscoveredModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')

  // Live input status calculation
  const trimmed = keyInput.trim()
  const isPrefixValid = trimmed.startsWith('nvapi-')
  const isKeyLengthValid = trimmed.length >= 16
  const isReadyToValidate = isPrefixValid && isKeyLengthValid

  // Handle key submission and validation
  async function handleValidate(event?: FormEvent) {
    if (event) event.preventDefault()
    if (!isReadyToValidate) {
      setError('Key must start with nvapi- and contain your full key token')
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
        body: JSON.stringify({ api_key: trimmed }),
      })

      if (!validateResult.valid) {
        setError(validateResult.reason || 'Invalid NVIDIA API key. Please check your credentials.')
        setStep('key_input')
        return
      }

      // Store key in browser storage and sync
      localStorage.setItem('pentagon.nvidiaKey', trimmed)
      try {
        await apiRequest('/api/keys', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, api_key: trimmed }),
        })
      } catch {
        // Safe to ignore backend sync if stored locally
      }

      // 2. Discover models associated with this key
      setStep('discovering')

      let models = validateResult.models || []
      let defModel = validateResult.default_model || ''

      if (!models.length) {
        try {
          const modelsResult = await apiRequest<{ models: ModelInfo[]; default_model?: string }>(
            '/api/models',
            { headers: { 'X-Nvidia-Key': trimmed } }
          )
          models = modelsResult.models || []
          defModel = modelsResult.default_model || ''
        } catch {
          // fallback
        }
      }

      // Smooth pacing transition for discovery experience
      await new Promise((resolve) => setTimeout(resolve, 850))

      if (models.length > 0) {
        setDiscoveredModels(models)
        setSelectedModel(defModel || models[0].id)
      }

      setStep('models_ready')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not validate with server')
      setStep('key_input')
    }
  }

  // Handle final workspace launch
  function handleLaunch() {
    const finalModel = selectedModel || discoveredModels[0]?.id || 'nvidia/llama-3.1-nemotron-70b-instruct'
    localStorage.setItem('pentagon.defaultModel', finalModel)
    onComplete({
      key: trimmed,
      models: discoveredModels,
      selectedModel: finalModel,
    })
  }

  return (
    <main className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-[#000000] px-4 py-8 text-zinc-100 selection:bg-emerald-400/20">
      {/* Calm ambient background graphic glow and geometric orbital rings */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="size-[540px] rounded-full bg-gradient-to-tr from-emerald-500/[0.08] via-teal-500/[0.03] to-transparent blur-[130px]" />
        <div className="absolute size-[320px] rounded-full border border-emerald-500/[0.04]" />
        <div className="absolute size-[480px] rounded-full border border-white/[0.02]" />
        <div className="absolute size-[640px] rounded-full border border-white/[0.015]" />
      </div>

      <section className="relative z-10 flex w-full max-w-[460px] flex-col items-center">
        {/* Sleek Centerpiece Logo Graphic with dynamic orbit for loading */}
        <div className="relative mb-6 flex items-center justify-center">
          <div className="absolute size-36 rounded-full bg-emerald-400/[0.16] blur-3xl transition duration-700" />
          
          {(step === 'validating' || step === 'discovering') && (
            <div className="absolute size-32 animate-spin rounded-full border border-dashed border-emerald-400/40" style={{ animationDuration: '6s' }} />
          )}

          <div className="relative flex size-24 items-center justify-center rounded-3xl border border-white/[0.12] bg-[#090a0d]/90 shadow-[0_24px_60px_rgba(0,0,0,0.85)] backdrop-blur-2xl ring-1 ring-white/[0.06]">
            <div className="absolute inset-0 rounded-3xl bg-gradient-to-b from-white/[0.08] to-transparent" />
            <LogomarkBadge size={60} className="transition duration-500 hover:scale-105" />
          </div>
        </div>

        {/* Step Indicator Pills */}
        <div className="mb-5 flex items-center gap-2">
          <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-micro font-medium transition ${
            step === 'key_input' ? 'border border-emerald-400/30 bg-emerald-400/10 text-emerald-300' : 'text-zinc-600'
          }`}>
            <span className={`size-1.5 rounded-full ${step === 'key_input' ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
            <span>1. API Key</span>
          </div>

          <span className="text-zinc-700">/</span>

          <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-micro font-medium transition ${
            step === 'validating' ? 'border border-amber-400/30 bg-amber-400/10 text-amber-300 animate-pulse' :
            step === 'discovering' || step === 'models_ready' ? 'border border-emerald-400/30 bg-emerald-400/10 text-emerald-300' : 'text-zinc-600'
          }`}>
            <span className={`size-1.5 rounded-full ${
              step === 'validating' ? 'bg-amber-400' :
              step === 'discovering' || step === 'models_ready' ? 'bg-emerald-400' : 'bg-zinc-700'
            }`} />
            <span>2. Validate</span>
          </div>

          <span className="text-zinc-700">/</span>

          <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-micro font-medium transition ${
            step === 'discovering' ? 'border border-cyan-400/30 bg-cyan-400/10 text-cyan-300 animate-pulse' :
            step === 'models_ready' ? 'border border-emerald-400/30 bg-emerald-400/10 text-emerald-300' : 'text-zinc-600'
          }`}>
            <span className={`size-1.5 rounded-full ${
              step === 'discovering' ? 'bg-cyan-400' :
              step === 'models_ready' ? 'bg-emerald-400' : 'bg-zinc-700'
            }`} />
            <span>3. Models</span>
          </div>
        </div>

        {/* Global Error Banner */}
        {error && (
          <div role="alert" className="mb-4 w-full rounded-xl border border-rose-500/25 bg-rose-500/[0.08] px-4 py-2.5 text-caption text-rose-300 backdrop-blur-md">
            {error}
          </div>
        )}

        {/* ----------------- STEP 1: KEY INPUT ----------------- */}
        {step === 'key_input' && (
          <div className="w-full text-center">
            <h1 className="text-hero font-semibold tracking-tight text-white">Enter NVIDIA Key</h1>
            <p className="mt-1 text-small text-zinc-400">
              Connect your API key to discover and run state-of-the-art models on NVIDIA NIM.
            </p>

            <form onSubmit={handleValidate} className="mt-5 w-full">
              <div className="group relative flex items-center rounded-2xl border border-white/[0.08] bg-white/[0.025] p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.5)] backdrop-blur-2xl transition-[border-color,box-shadow,background-color] duration-300 hover:border-white/[0.14] focus-within:border-emerald-400/40 focus-within:bg-[#080808] focus-within:shadow-[0_0_35px_rgba(16,185,129,0.12)]">
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
                  <span className={`size-1.5 rounded-full ${
                    !trimmed ? 'bg-zinc-700' : isReadyToValidate ? 'bg-emerald-400' : 'bg-amber-400'
                  }`} />
                  <span>
                    {!trimmed ? 'Starts with nvapi-' : isReadyToValidate ? 'Ready to validate' : 'Incomplete key'}
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
            </form>
          </div>
        )}

        {/* ----------------- STEP 2: VALIDATING ----------------- */}
        {step === 'validating' && (
          <div className="flex w-full flex-col items-center py-4 text-center">
            <div className="relative mb-3 flex items-center justify-center">
              <LoaderCircle size={28} className="animate-spin text-emerald-400" />
            </div>
            <h2 className="text-body font-semibold text-white">Validating with NVIDIA NIM</h2>
            <p className="mt-1 text-small text-zinc-400">Verifying authorization and key permissions...</p>
            <div className="mt-5 h-1 w-48 overflow-hidden rounded-full bg-white/[0.08]">
              <div className="h-full w-2/3 animate-pulse rounded-full bg-gradient-to-r from-emerald-500 to-teal-400" />
            </div>
          </div>
        )}

        {/* ----------------- STEP 3: DISCOVERING MODELS ----------------- */}
        {step === 'discovering' && (
          <div className="flex w-full flex-col items-center py-4 text-center">
            <div className="relative mb-3 flex items-center justify-center">
              <div className="grid size-10 place-items-center rounded-xl border border-cyan-500/20 bg-cyan-500/10 text-cyan-300">
                <Cpu size={20} className="animate-pulse" />
              </div>
            </div>
            <h2 className="text-body font-semibold text-white">Discovering Models</h2>
            <p className="mt-1 text-small text-zinc-400">Scanning available chat, vision, and reasoning models...</p>

            {/* Skeleton Model Discovery Preview */}
            <div className="mt-5 w-full space-y-2">
              <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 animate-pulse">
                <div className="flex items-center gap-2">
                  <span className="size-2 rounded-full bg-emerald-400/80" />
                  <div className="h-3.5 w-32 rounded bg-white/10" />
                </div>
                <div className="h-3 w-16 rounded bg-white/10" />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 animate-pulse" style={{ animationDelay: '150ms' }}>
                <div className="flex items-center gap-2">
                  <span className="size-2 rounded-full bg-cyan-400/80" />
                  <div className="h-3.5 w-28 rounded bg-white/10" />
                </div>
                <div className="h-3 w-14 rounded bg-white/10" />
              </div>
            </div>
          </div>
        )}

        {/* ----------------- STEP 4: MODELS READY ----------------- */}
        {step === 'models_ready' && (
          <div className="w-full text-center">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-caption text-emerald-300">
              <ShieldCheck size={14} className="text-emerald-400" />
              <span>{discoveredModels.length} Models Ready</span>
            </div>

            <h1 className="mt-2 text-hero font-semibold text-white">Select Default Model</h1>
            <p className="mt-1 text-small text-zinc-400">
              Choose your starting model. You can switch between any of them anytime in chat.
            </p>

            {/* Discovered Models List */}
            <div className="mt-4 max-h-[260px] w-full space-y-2 overflow-y-auto pr-1 text-left custom-scrollbar">
              {discoveredModels.map((model) => {
                const isSelected = model.id === selectedModel
                const family = getModelFamily(model.id)
                const isReasoning = model.is_reasoning || model.id.includes('r1')
                const isVision = model.supports_vision || model.id.includes('vision')

                return (
                  <button
                    key={model.id}
                    type="button"
                    onClick={() => setSelectedModel(model.id)}
                    className={`group flex w-full items-center justify-between rounded-2xl border p-3 text-left transition ${
                      isSelected
                        ? 'border-emerald-500/50 bg-emerald-500/[0.08] shadow-[0_0_20px_rgba(16,185,129,0.12)] ring-1 ring-emerald-500/30'
                        : 'border-white/[0.08] bg-white/[0.02] hover:border-white/[0.16] hover:bg-white/[0.04]'
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

                    <div className={`grid size-6 shrink-0 place-items-center rounded-full border transition ${
                      isSelected
                        ? 'border-emerald-400 bg-emerald-400 text-black'
                        : 'border-white/[0.15] bg-transparent text-transparent group-hover:border-white/[0.3]'
                    }`}>
                      <Check size={13} strokeWidth={2.8} />
                    </div>
                  </button>
                )
              })}
            </div>

            {/* Launch Action */}
            <div className="mt-5 flex flex-col items-center gap-2">
              <button
                type="button"
                onClick={handleLaunch}
                className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 font-medium text-black shadow-[0_0_24px_rgba(52,211,153,0.3)] transition hover:bg-emerald-300 active:scale-95"
              >
                <Sparkles size={16} />
                <span>Launch Pentagon Workspace</span>
                <ArrowRight size={16} />
              </button>

              <button
                type="button"
                onClick={() => setStep('key_input')}
                className="text-micro text-zinc-500 transition hover:text-zinc-300"
              >
                Change API key
              </button>
            </div>
          </div>
        )}
      </section>
    </main>
  )
}
