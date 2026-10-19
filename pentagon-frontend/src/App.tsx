import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import {
  ArrowUp,
  Check,
  ChevronDown,
  Copy,
  FileSpreadsheet,
  FileText,
  Globe,
  Image as ImageIcon,
  LoaderCircle,
  Key,
  LockKeyhole,
  MapPin,
  Menu,
  Mic,
  Paperclip,
  Plus,
  Presentation,
  Settings,
  Sparkles,
  Square,
  Video,
  X,
} from 'lucide-react'
import { apiRequest, clearStoredNvidiaKey, getLocalUserId, getStoredNvidiaKey } from './api'
import { getCachedLocation, requestGpsLocation, clearLocation, type UserLocation } from './lib/deviceContext'
import { KeyActivationFlow } from './components/KeyActivationFlow'
import { useCommandSettings } from './hooks/useCommandSettings'
import { useAutonomy } from './hooks/useAutonomy'
import { useAgentBadges } from './hooks/useAgentBadges'
import { usePendingApprovals, usePendingCommands } from './hooks/usePendingApprovals'
import { useChatStream } from './hooks/useChatStream'
import { useAudioUrls } from './hooks/useAudioUrls'
import { useAmbientSignals } from './hooks/useAmbientSignals'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import type { ConversationDetail, TranscriptInfo } from './hooks/types/app'
import { AssistantDetails } from './components/MessageContent'
import { CommandApproval, CommandLog } from './components/CommandPanel'
import { Sidebar } from './components/Sidebar'
import { Logomark, LogomarkBadge } from './components/Logomark'
import { ThinkingIndicator } from './components/ThinkingIndicator'
import { AmbientLayer } from './components/AmbientLayer'
import { AgentActivity } from './components/AgentActivity'
import { ModelSelector } from './components/ModelSelector'
import { AVATAR_THEMES, getPreferences, subscribePreferences } from './lib/preferences'
import type { ChatMessage, Conversation, DocumentInfo, ModelInfo } from './types'

const CommandPalette = lazy(() => import('./components/CommandPalette').then((m) => ({ default: m.CommandPalette })))
const SettingsDialog = lazy(() => import('./components/SettingsDialog').then((m) => ({ default: m.SettingsDialog })))
const WorkflowDesigner = lazy(() => import('./components/WorkflowDesigner').then((m) => ({ default: m.WorkflowDesigner })))

const DASHBOARD_ACTIONS = [
  {
    icon: FileText,
    badge: 'Executive Proposal',
    tag: '.docx',
    title: 'Enterprise Business Proposal',
    prompt: 'Create a comprehensive 5-page enterprise SaaS business proposal with executive summary, market analysis, financial projections, and implementation roadmap as a Word document (.docx).',
    agent: true,
  },
  {
    icon: FileSpreadsheet,
    badge: 'Financial Model',
    tag: '.xlsx',
    title: 'SaaS Revenue & Cohorts',
    prompt: 'Build a multi-year SaaS financial model spreadsheet with monthly revenue forecasts, customer cohorts, CAC/LTV calculations, and EBITDA summaries (.xlsx).',
    agent: true,
  },
  {
    icon: Presentation,
    badge: 'Pitch Deck',
    tag: '.pptx',
    title: 'Investor Slide Deck',
    prompt: 'Generate an engaging 10-slide startup pitch deck presentation covering the problem, solution, market size, product demo, unit economics, and team (.pptx).',
    agent: true,
  },
  {
    icon: Globe,
    badge: 'Web Synthesis',
    tag: 'Web',
    title: 'Frontier AI Research Report',
    prompt: 'Perform deep research on current 2026 breakthroughs in agentic AI architectures and multi-step reasoning models, synthesizing verified findings and citations.',
    agent: true,
  },
]

function titleFor(message: string) {
  const normalized = message.trim().replace(/\s+/g, ' ')
  return normalized.length > 54 ? `${normalized.slice(0, 51)}…` : normalized || 'New thread'
}

function isDocument(file: File) {
  return /\.(pdf|docx?|pptx?|xlsx?|csv|tsv|txt|md|markdown|json|ya?ml|html?|xml|rst|py|js|ts|tsx|jsx|sh|sql|log)$/i.test(file.name)
}

function isImage(file: File) {
  return file.type.startsWith('image/') || /\.(jpe?g|png|webp)$/i.test(file.name)
}

function isVideo(file: File) {
  return file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi)$/i.test(file.name)
}

/**
 * Which model a new thread should start on.
 *
 * The server's default is only a preference, not a guarantee: it is a single
 * `DEFAULT_CHAT_MODEL` setting shared by every key, while the picker is built
 * from the catalog of whichever key is stored. When the two disagree, taking
 * the server default anyway leaves the picker displaying one model while every
 * request quietly sends another -- so it is only accepted when it is actually
 * on offer.
 */
const DEFAULT_NVIDIA_MODELS: ModelInfo[] = [
  { id: 'nvidia/llama-3.1-nemotron-70b-instruct', supports_vision: false, context_window: 131072 },
  { id: 'meta/llama-3.2-11b-vision-instruct', supports_vision: true, context_window: 131072 },
  { id: 'meta/llama-3.2-90b-vision-instruct', supports_vision: true, context_window: 131072 },
  { id: 'mistralai/mistral-large-2-instruct', supports_vision: false, context_window: 131072 },
  { id: 'deepseek-ai/deepseek-v4.1-flash', supports_vision: false, context_window: 65536 },
]

function chooseDefaultModel(available: ModelInfo[], preferred: string, serverDefault: string): string {
  if (preferred && available.some((model) => model.id === preferred)) return preferred
  if (serverDefault && available.some((model) => model.id === serverDefault)) return serverDefault
  return available[0]?.id || ''
}

function App() {
  const [userId] = useState(getLocalUserId)
  const [booting, setBooting] = useState(true)
  const [keyNeeded, setKeyNeeded] = useState(false)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  const [threads, setThreads] = useState<Conversation[]>([])
  const [active, setActive] = useState<ConversationDetail | Conversation | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  // The summary flag is still set wherever a thread is opened or switched, so
  // it is kept tracked even though no surface reads it today. Dropping it would
  // leave those call sites silently wrong if the indicator ever comes back.
  const [, setSummaryActive] = useState(false)
  const [queuedDocuments, setQueuedDocuments] = useState<File[]>([])
  const [media, setMedia] = useState<File | null>(null)
  const [selectedModel, setSelectedModel] = useState('')
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [transcriptInfo, setTranscriptInfo] = useState<TranscriptInfo | null>(null)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [atBottom, setAtBottom] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [composerFocused, setComposerFocused] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [stoppedReply, setStoppedReply] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const { commandSettings, setCommandSettings, loadCommandSettings } = useCommandSettings(userId)
  const { autonomySettings, load: loadAutonomySettings, changeSetting: changeAutonomySetting, changePreset: changeAutonomyPreset } = useAutonomy(userId)
  const { badges: agentBadges, refresh: refreshBadges } = useAgentBadges()
  const [deciding, setDeciding] = useState<string | null>(null)
  const [settingsTab, setSettingsTab] = useState<'Account' | 'Permissions' | 'Advanced'>('Account')
  const [settingsSection, setSettingsSection] = useState<'Skills' | 'MCP Servers' | 'Commands' | 'Data' | 'Appearance' | 'Model' | 'Audit log' | 'About' | undefined>(undefined)
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  const userName = prefs.userName.trim()
  // Agent mode: the same composer, a different route. The agent loop's events
  // (tool timeline, plan, approvals, questions, artifacts) render under the
  // answer instead of the graph's plain token stream. The choice is ours to
  // remember across reloads -- it is a way of working, not a per-turn flag.
  const [agentMode] = useState(() => {
    try { return window.localStorage.getItem('pentagon.agentMode') === '1' } catch { return false }
  })
  const [viewMode, setViewMode] = useState<'chat' | 'workflows'>('chat')
  const [canRetry, setCanRetry] = useState(false)
  const [userLocation, setUserLocation] = useState<UserLocation | null>(() => getCachedLocation())
  const [locating, setLocating] = useState(false)

  const handleToggleLocation = useCallback(async () => {
    if (userLocation) {
      clearLocation()
      setUserLocation(null)
      setNotice('GPS location turned off. Pentagon will use network-based estimate if needed.')
      return
    }
    setLocating(true)
    try {
      const loc = await requestGpsLocation()
      if (loc) {
        setUserLocation(loc)
        const place = [loc.city, loc.region, loc.country].filter(Boolean).join(', ')
        setNotice(`GPS location active: ${place || `${loc.latitude.toFixed(4)}, ${loc.longitude.toFixed(4)}`}`)
      } else {
        setError('Location permission was denied or unavailable.')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to obtain GPS location')
    } finally {
      setLocating(false)
    }
  }, [userLocation])

  // Saving a level sends the current `enabled` alongside it, because the one
  // endpoint owns both fields. The response replaces local state wholesale so
  // the badge and the radio can never show a level the server did not accept.
  const fileInput = useRef<HTMLInputElement>(null)
  const answeredLocation = useRef<string | null>(null)

  /**
   * Answer the server's question with a position, or with nothing.
   *
   * The permission prompt belongs to this window, and a refusal is a normal
   * answer rather than an error: the backend already treats "no answer" as
   * permission to fall back to a coarse network estimate.
   */
  const answerLocationRequest = useCallback(async (requestId: string) => {
    const send = async (approved: boolean, value?: Record<string, unknown>) => {
      try {
        await apiRequest('/api/commands/decide', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_id: requestId, approved, user_id: userId, value: value ?? {} }),
        })
      } catch {
        /* The turn continues without a location; nothing to retry. */
      }
    }
    if (!navigator.geolocation) {
      await send(false)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        void send(true, {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_m: position.coords.accuracy,
        })
      },
      () => { void send(false) },
      { enableHighAccuracy: false, timeout: 20000, maximumAge: 60000 },
    )
  }, [userId])
  const recorder = useRef<MediaRecorder | null>(null)
  const streamAbort = useRef<AbortController | null>(null)
  const currentAssistantIndex = useRef(0)
  const conversationViewport = useRef<HTMLDivElement>(null)
  const followConversation = useRef(true)
  const openThreadToken = useRef(0)
  const scrollFrame = useRef<number | null>(null)
  // Blob URLs for synthesised replies. A WAV is megabytes, and pcmToWavUrl
  // handed out a fresh object URL per answer that nothing ever released, so a
  // long session with speech grew without bound. Registered on creation and
  // revoked below once no message points at them any more.
  const audioUrls = useRef<Set<string>>(new Set())
  const loadThreadRef = useRef<(id: string) => Promise<void>>(() => Promise.resolve())
  const isDraftThread = Boolean(active && 'isDraft' in active && active.isDraft)
  const chat = useChatStream({
    userId,
    agentMode,
    hasActiveThread: Boolean(active),
    isDraftThread,
    selectedModel,
    streaming,
    transcribing,
    uploading,
    draft,
    setDraft,
    media,
    setMedia,
    queuedDocuments,
    setQueuedDocuments,
    transcriptInfo,
    setTranscriptInfo,
    messages,
    setMessages,
    setActive,
    setStreaming,
    setStoppedReply,
    setNotice,
    setError,
    setCanRetry,
    setDeciding,
    deciding,
    setRecording,
    setTranscribing,
    recording,
    followConversation,
    streamAbort,
    createRemoteThread,
    refreshThreads,
    refreshBadges,
    uploadDocument,
    acceptFiles,
    documents,
    onAudioUrl: (url) => {
      audioUrls.current.add(url)
    },
    onApprovalResolved: (id) => {
      void loadThreadRef.current(id)
    },
  })

  const activeId = active?.id || null
  const sidebarThreads = active && 'isDraft' in active && active.isDraft ? [active as Conversation, ...threads] : threads
  const conversationAnnouncement = useMemo(() => {
    if (transcribing) return 'Transcribing your recording.'
    if (uploading) return 'Uploading a document.'
    if (switching) return 'Switching model.'
    if (streaming) return stoppedReply ? 'Stopping the reply.' : 'Pentagon is replying.'
    const last = messages[messages.length - 1]
    if (last?.role !== 'assistant' || !last.content) return ''
    return stoppedReply ? 'Reply stopped.' : 'Reply finished.'
  }, [streaming, transcribing, uploading, switching, messages, stoppedReply])

  const handleKeyActivationComplete = useCallback(
    ({
      models: discovered,
      selectedModel: chosen,
    }: {
      key: string
      models: ModelInfo[]
      selectedModel: string
    }) => {
      if (discovered && discovered.length > 0) {
        setModels(discovered)
      }
      if (chosen) {
        setSelectedModel(chosen)
        setDefaultModel(chosen)
      }
      setKeyNeeded(false)
    },
    [],
  )

  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      setBooting(true)
      let preferredModel = ''
      let list: Conversation[] = []
      if (typeof window !== 'undefined') {
        const urlParams = new URLSearchParams(window.location.search)
        if (urlParams.has('reset') || urlParams.has('clear') || urlParams.has('logout') || urlParams.has('setup')) {
          clearStoredNvidiaKey()
          window.history.replaceState({}, document.title, window.location.pathname)
        }
        // Purge legacy key so every user is prompted afresh
        if (localStorage.getItem('pentagon.nvidiaKey')) {
          localStorage.removeItem('pentagon.nvidiaKey')
        }
      }

      const localKey = getStoredNvidiaKey()

      if (!localKey) {
        if (!cancelled) {
          setKeyNeeded(true)
          setBooting(false)
        }
        return
      }

      try {
        // Whether the shell tool is available is fixed for the session, so it
        // belongs in the one bootstrap fetch rather than in an effect of its
        // own. It is deliberately not fatal: a failure here must not stop the
        // app from loading models and threads, and the toggle simply stays off.
        await loadCommandSettings()
        await loadAutonomySettings()
        await refreshBadges()
        const modelResult = await apiRequest<{ models: ModelInfo[]; default_model?: string | null }>(`/api/models?user_id=${encodeURIComponent(userId)}`)
        if (cancelled) return
        setModels(modelResult.models)
        const storedModel = getPreferences().defaultModel
        preferredModel = chooseDefaultModel(
          modelResult.models,
          storedModel,
          modelResult.default_model || '',
        )
        setDefaultModel(preferredModel)
        list = await apiRequest<Conversation[]>('/api/conversations?user_id=' + encodeURIComponent(userId))
        if (cancelled) return
        setThreads(list)
        if (list.length) {
          const [detail, docs] = await Promise.all([
            apiRequest<ConversationDetail>(`/api/conversations/${encodeURIComponent(list[0].id)}?user_id=${encodeURIComponent(userId)}`),
            apiRequest<DocumentInfo[]>(`/api/documents?user_id=${encodeURIComponent(userId)}&conversation_id=${encodeURIComponent(list[0].id)}`),
          ])
          if (cancelled) return
          setActive(detail)
          setMessages(detail.messages)
          setDocuments(docs)
          setSummaryActive(Boolean(detail.summary_at_switch))
          setSelectedModel(detail.active_model || preferredModel)
        } else {
          setActive(null)
          setMessages([])
          setDocuments([])
          setSummaryActive(false)
          setSelectedModel(preferredModel)
        }
        setKeyNeeded(false)
      } catch {
        if (cancelled) return
        setModels(DEFAULT_NVIDIA_MODELS)
        const def = DEFAULT_NVIDIA_MODELS[0].id
        setSelectedModel(def)
        setDefaultModel(def)
        const currentKey = getStoredNvidiaKey()
        setKeyNeeded(!currentKey)
      } finally {
        if (!cancelled) setBooting(false)
      }
    }
    void hydrate()
    return () => { cancelled = true }
  }, [userId, loadCommandSettings, refreshBadges, loadAutonomySettings])

  useEffect(() => {
    if (!followConversation.current || !conversationViewport.current) return
    if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current)
    scrollFrame.current = requestAnimationFrame(() => {
      const viewport = conversationViewport.current
      viewport?.scrollTo({ top: viewport.scrollHeight, behavior: streaming ? 'auto' : 'smooth' })
      scrollFrame.current = null
    })
    return () => {
      if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current)
      scrollFrame.current = null
    }
  }, [messages, streaming])
  useEffect(() => () => recorder.current?.stream.getTracks().forEach((track) => track.stop()), [])

  usePendingCommands(
    userId,
    streaming ? (active?.id ?? null) : null,
    commandSettings.enabled,
    {
      onLocationRequest: (requestId) => {
        if (answeredLocation.current === requestId) return
        answeredLocation.current = requestId
        // Only the window can ask the user for a fix, so the permission
        // prompt belongs here rather than in the backend. Declining simply
        // answers with nothing, and the server falls back to the network
        // estimate.
        void answerLocationRequest(requestId)
      },
      onShowable: (showable) => {
        setMessages((current) =>
          current.map((item) =>
            item.role === 'assistant' && !item.pendingCommand && !item.content
              ? { ...item, pendingCommand: showable }
              : item,
          ),
        )
      },
      onProgress: () => {},
    },
  )

  // Live approval-queue banner. Unlike the older command-only prompt, this reads
  // the new /api/pending-approvals endpoint, which surfaces the autonomy gate's
  // interrupt card (the always_ask / ask_first_time branch) anywhere in the app.
  const { pending: pendingApprovals, error: pendingApprovalsError, dismiss: dismissPendingApproval } =
    usePendingApprovals(userId, active?.id ?? null, (approval, _approved) => {
      const targetId = approval.conversation_id || active?.id
      if (targetId) {
        void loadThread(targetId)
      }
    })
  useEffect(() => () => streamAbort.current?.abort(), [])
  useAudioUrls(messages)
  useAmbientSignals({
    streaming,
    streamingWithContent: Boolean(messages[messages.length - 1]?.content),
    transcribing,
    uploading,
    switching,
    error,
    composerFocused,
    lastMessageHasContent: Boolean(messages[messages.length - 1]?.content),
  })

  useKeyboardShortcuts({
    active: Boolean(active),
    onTogglePalette: () => setPaletteOpen((value) => !value),
    onNewThread: () => startThread(),
    onJumpToMessage: (offset) => jumpToMessage(offset),
    onFocusComposer: () => document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Write a message"]')?.focus(),
  })

  function handleConversationScroll() {
    const viewport = conversationViewport.current
    if (!viewport) return
    followConversation.current = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 120
    setAtBottom(followConversation.current)
  }

  function jumpToLatest() {
    const viewport = conversationViewport.current
    if (!viewport) return
    followConversation.current = true
    setAtBottom(true)
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: 'smooth' })
  }

  function jumpToMessage(offset: number) {
    const viewport = conversationViewport.current
    if (!viewport) return
    const rows = Array.from(viewport.querySelectorAll<HTMLElement>('[data-assistant-message]'))
    if (!rows.length) return
    const index = Math.min(Math.max(currentAssistantIndex.current + offset, 0), rows.length - 1)
    currentAssistantIndex.current = index
    rows[index].scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  async function copyMessage(message: ChatMessage) {
    if (!message.content) return
    try {
      await navigator.clipboard.writeText(message.content)
      setCopiedId(message.id)
      window.setTimeout(() => setCopiedId(null), 1600)
    } catch {
      setError('Could not copy to the clipboard.')
    }
  }

  async function refreshThreads() {
    const list = await apiRequest<Conversation[]>(`/api/conversations?user_id=${encodeURIComponent(userId)}`)
    setThreads(list)
    return list
  }

  async function renameThread(id: string, title: string) {
    setError('')
    try {
      const updated = await apiRequest<Conversation>(
        `/api/conversations/${encodeURIComponent(id)}/title?user_id=${encodeURIComponent(userId)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title }),
        },
      )
      setThreads((current) => current.map((thread) => (thread.id === id ? updated : thread)))
      setActive((current) => (current && current.id === id ? { ...current, title: updated.title } : current))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not rename the thread.')
    }
  }

  async function deleteThread(id: string) {
    setError('')
    try {
      await apiRequest(`/api/conversations/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`, { method: 'DELETE' })
      const remaining = threads.filter((thread) => thread.id !== id)
      setThreads(remaining)
      if (active?.id === id) {
        // A reply in flight is still streaming into this thread, and would keep
        // appending to it after the server had already dropped it. Stop it, then
        // move on regardless of the streaming guard openThread applies.
        streamAbort.current?.abort()
        const next = remaining[0]
        if (next) {
          void loadThread(next.id)
        } else {
          // Nothing left to show: fall back to an empty draft thread.
          setActive({
            id: `draft-${crypto.randomUUID()}`,
            title: 'New Thread',
            updated_at: new Date().toISOString(),
            active_model: null,
            isDraft: true,
          })
          setMessages([])
          setDocuments([])
          setSummaryActive(false)
        }
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not delete the thread.')
    }
  }

  /** Re-reads the model list after the API key changes, without a reload. */
  async function refreshModels() {
    try {
      const result = await apiRequest<{ models: ModelInfo[]; default_model?: string | null }>(
        `/api/models?user_id=${encodeURIComponent(userId)}`,
      )
      setModels(result.models)
      setDefaultModel(result.default_model || '')
      setKeyNeeded(false)
      // A different key serves a different catalog. If the model this thread is
      // pinned to is no longer on offer, keeping it would show one name in the
      // picker while the request sent another, so fall back to a real one.
      setSelectedModel((current) =>
        result.models.some((model) => model.id === current)
          ? current
          : chooseDefaultModel(result.models, getPreferences().defaultModel, result.default_model || ''),
      )
    } catch {
      /* Keep the previous list; the next send will surface any real problem. */
    }
  }

  function startThread() {
    if (streaming) return
    followConversation.current = true
    // Abandon any thread still loading, so it cannot overwrite this new draft.
    openThreadToken.current += 1
    setError('')
    setNotice('')
    setActive({
      id: `draft-${crypto.randomUUID()}`,
      title: 'New Thread',
      updated_at: new Date().toISOString(),
      active_model: null,
      isDraft: true,
    })
    setMessages([])
    setDocuments([])
    setSummaryActive(false)
    setQueuedDocuments([])
    setMedia(null)
    setDraft('')
    setTranscriptInfo(null)
    // A draft has no model of its own, so it falls back to the default chosen
    // in Settings rather than inheriting whatever the previous thread used.
    setSelectedModel(chooseDefaultModel(models, getPreferences().defaultModel, defaultModel))
  }

  async function openThread(id: string) {
    if (streaming || switching) return
    setError('')
    setNotice('')
    await loadThread(id)
  }

  /**
   * The fetch-and-apply half of openThread, deliberately without the streaming
   * guard. Deleting the open thread has to replace it even mid-reply, and
   * reusing the guarded entry point there left the app showing a thread that
   * no longer existed.
   */
  async function loadThread(id: string) {
    // Clicking through threads quickly starts overlapping loads. Only the most
    // recent click may write to state, otherwise a slow earlier response can
    // land last and show the wrong conversation.
    const token = ++openThreadToken.current
    try {
      const [detail, docs] = await Promise.all([
        apiRequest<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`),
        apiRequest<DocumentInfo[]>(`/api/documents?user_id=${encodeURIComponent(userId)}&conversation_id=${encodeURIComponent(id)}`),
      ])
      if (token !== openThreadToken.current) return
      followConversation.current = true
      setActive(detail)
      setMessages(detail.messages)
      setDocuments(docs)
      setSummaryActive(Boolean(detail.summary_at_switch))
      setSelectedModel(detail.active_model || chooseDefaultModel(models, '', defaultModel))
      setQueuedDocuments([])
      setMedia(null)
      setDraft('')
      setTranscriptInfo(null)
    } catch (cause) {
      if (token !== openThreadToken.current) return
      setError(cause instanceof Error ? cause.message : 'Could not load this thread.')
    }
  }
  loadThreadRef.current = loadThread

  async function createRemoteThread(firstMessage: string): Promise<ConversationDetail> {
    if (active && !isDraftThread) return active as ConversationDetail
    const created = await apiRequest<Conversation>('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, title: titleFor(firstMessage) }),
    })
    const remote = { ...created, summary_at_switch: null, messages: [] } as ConversationDetail
    setActive(remote)
    setSummaryActive(false)
    setThreads((items) => [remote, ...items])
    return remote
  }

  async function loadDocuments(conversationId: string) {
    try {
      const result = await apiRequest<DocumentInfo[]>(`/api/documents?user_id=${encodeURIComponent(userId)}&conversation_id=${encodeURIComponent(conversationId)}`)
      if (Array.isArray(result) && result.length > 0) {
        setDocuments(result)
        try { sessionStorage.setItem(`pentagon_docs_${conversationId}`, JSON.stringify(result)) } catch {}
        return result
      }
    } catch {
      // ignore
    }
    try {
      const cached = sessionStorage.getItem(`pentagon_docs_${conversationId}`)
      if (cached) {
        const parsed = JSON.parse(cached) as DocumentInfo[]
        if (Array.isArray(parsed) && parsed.length > 0) {
          setDocuments(parsed)
          return parsed
        }
      }
    } catch {}
    setDocuments([])
    return []
  }

  async function uploadDocument(file: File, conversationId: string) {
    const form = new FormData()
    form.set('user_id', userId)
    form.set('conversation_id', conversationId)
    form.set('file', file)
    try {
      if (file.size < 5 * 1024 * 1024) {
        const text = await file.text()
        if (text && !text.includes('\x00\x00\x00')) {
          form.set('file_text', text)
        }
      }
    } catch {
      // binary file, ignore text pre-extraction
    }
    const result = await apiRequest<DocumentInfo>('/api/documents/upload', { method: 'POST', body: form })
    const list = await loadDocuments(conversationId)
    if (!list.some((d) => d.document_id === result.document_id)) {
      const merged = [...list, result]
      setDocuments(merged)
      try { sessionStorage.setItem(`pentagon_docs_${conversationId}`, JSON.stringify(merged)) } catch {}
    }
    setNotice(`${result.filename} added to this thread.`)
  }

  async function switchModel(nextModel: string) {
    if (!nextModel || nextModel === selectedModel || switching) return
    const previous = selectedModel
    setSelectedModel(nextModel)
    setError('')
    if (!active || isDraftThread) return
    setSwitching(true)
    try {
      const result = await apiRequest<{ active_model: string; summary_generated: boolean; summary_word_count: number }>(
        `/api/conversations/${encodeURIComponent(active.id)}?user_id=${encodeURIComponent(userId)}`,
        { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: nextModel }) },
      )
      setThreads((items) => items.map((item) => item.id === active.id ? { ...item, active_model: result.active_model } : item))
      setActive((item) => item && item.id === active.id ? { ...item, active_model: result.active_model } : item)
      setSummaryActive(result.summary_generated)
      if (result.summary_generated) setNotice(`Context summary prepared for ${result.active_model} (${result.summary_word_count} words).`)
    } catch (cause) {
      setSelectedModel(previous)
      setError(cause instanceof Error ? cause.message : 'Could not change this thread’s model.')
    } finally { setSwitching(false) }
  }

  async function acceptFiles(files: File[]) {
    const accepted: File[] = []
    let nextMedia: File | null = null
    for (const file of files) {
      if (isDocument(file)) accepted.push(file)
      else if (isImage(file) || isVideo(file)) nextMedia = file
      else setError(`${file.name} is not a supported file format.`)
    }
    if (nextMedia) setMedia(nextMedia)
    if (!accepted.length) return
    if (!active) {
      setQueuedDocuments((current) => [...current, ...accepted])
      setNotice(`${accepted.length} document${accepted.length === 1 ? '' : 's'} queued for the first message.`)
      return
    }
    if (isDraftThread) {
      setQueuedDocuments((current) => [...current, ...accepted])
      setNotice(`${accepted.length} document${accepted.length === 1 ? '' : 's'} queued for the first message.`)
      return
    }
    setUploading(true)
    setError('')
    try {
      for (const file of accepted) await uploadDocument(file, active.id)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Document upload failed.') }
    finally { setUploading(false) }
  }

  function focusSearch() {
    document.querySelector<HTMLInputElement>('input[aria-label="Search conversations"]')?.focus()
  }


  if (booting) {
    return (
      <div className="grid h-full min-h-dvh place-items-center bg-[#000000]">
        <div className="relative flex items-center justify-center">
          <div className="absolute size-28 rounded-full bg-emerald-400/[0.15] blur-2xl animate-pulse" />
          <LogomarkBadge size={54} />
        </div>
      </div>
    )
  }

  if (keyNeeded) {
    return (
      <KeyActivationFlow
        userId={userId}
        initialKey={getStoredNvidiaKey()}
        onComplete={handleKeyActivationComplete}
      />
    )
  }

  return <div className="flex h-dvh min-h-[620px] overflow-hidden bg-transparent text-zinc-100 selection:bg-emerald-300/30">
    <AmbientLayer />
    {sidebarOpen ? (
      <button
        type="button"
        aria-label="Close navigation"
        onClick={() => setSidebarOpen(false)}
        className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm md:hidden"
      />
    ) : null}
    <Sidebar
      conversations={sidebarThreads}
      userId={userId}
      onOpenPalette={() => {
        setPaletteOpen(true)
        setSidebarOpen(false)
      }}
      onOpenSettings={(tab) => {
        if (tab) setSettingsTab(tab)
        setSettingsOpen(true)
        setSidebarOpen(false)
      }}
      open={sidebarOpen}
      onClose={() => setSidebarOpen(false)}
      activeId={activeId}
      query={search}
      onQueryChange={setSearch}
      onNewThread={startThread}
      onRename={(id, title) => void renameThread(id, title)}
      onDelete={(id) => void deleteThread(id)}
      onSelect={(id) => {
        if (isDraftThread && active?.id === id) return
        setSidebarOpen(false)
        void openThread(id)
      }}
    />
    <main className="relative flex min-w-0 flex-1 flex-col">
      <header className="z-20 flex min-h-[66px] items-center justify-between gap-2 border-b border-white/[0.065] bg-[#000000]/90 px-3 pt-[env(safe-area-inset-top)] backdrop-blur-xl sm:gap-3 sm:px-5 lg:px-7">
        <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open navigation"
            aria-expanded={sidebarOpen}
            className="grid size-9 shrink-0 place-items-center rounded-lg border border-white/[0.07] text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-100 md:hidden"
          >
            <Menu size={16} />
          </button>

          <ModelSelector
            models={models}
            selectedModel={selectedModel}
            onSelectModel={(id) => void switchModel(id)}
            disabled={!models.length || switching || streaming}
            switching={switching}
            agentBadge={agentBadges[selectedModel]?.badge}
          />
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => setKeyNeeded(true)}
            aria-label="NVIDIA API Key"
            title="Manage or re-enter NVIDIA API Key"
            className="flex h-9 items-center gap-1.5 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.07] px-2.5 text-caption font-medium text-emerald-400 transition duration-150 hover:border-emerald-500/40 hover:bg-emerald-500/15 hover:text-emerald-300"
          >
            <Key size={13} className="text-emerald-400" />
            <span className="hidden sm:inline">API Key</span>
          </button>
          <button
            type="button"
            onClick={startThread}
            aria-label="New thread"
            title="New thread (⌘N)"
            className="flex h-9 items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 text-small text-zinc-300 transition duration-150 hover:border-emerald-400/30 hover:bg-white/[0.06] hover:text-white"
          >
            <Plus size={15} className="text-emerald-400" />
            <span className="hidden sm:inline">New Thread</span>
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open settings"
            title="Settings & Capabilities"
            className="grid size-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.03] text-zinc-400 transition duration-150 hover:border-white/[0.16] hover:bg-white/[0.06] hover:text-zinc-100"
          >
            <Settings size={16} />
          </button>
        </div>
      </header>

      {viewMode === 'workflows' ? (
        <Suspense fallback={<div className="flex h-full min-h-0 flex-1 items-center justify-center text-xs text-zinc-500">Loading Workflow Studio...</div>}>
          <WorkflowDesigner
            userId={userId}
            onClose={() => setViewMode('chat')}
          />
        </Suspense>
      ) : (
      <section
        id="workspace-panel-Chat"
        role="region"
        aria-label="Conversation"
        className="relative flex min-h-0 flex-1 flex-col"
      >
        {(!atBottom && messages.length > 0) ? <button type="button" onClick={jumpToLatest} className="panel-enter absolute bottom-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-white/[0.1] bg-[#0f0f0f]/95 px-3 py-1.5 text-micro text-zinc-300 shadow-[0_10px_30px_rgba(0,0,0,.45)] backdrop-blur transition hover:border-emerald-300/30 hover:text-zinc-100">
          <ChevronDown size={12} className="rotate-180" />Jump to latest
        </button> : null}
        <div ref={conversationViewport} onScroll={handleConversationScroll} className="flex min-h-0 flex-1 flex-col overflow-y-auto" aria-label="Conversation" role="log" aria-live="off">
          <div className="mx-auto flex w-full max-w-[980px] 2xl:max-w-[1140px] flex-1 flex-col px-4 pb-5 pt-5 sm:px-7 sm:pt-8">
            {notice && <div role="status" className="mb-4 flex items-center justify-between rounded-lg border border-emerald-300/10 bg-emerald-300/[0.04] px-3 py-2 text-small text-emerald-100/80"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss notice"><X size={13} /></button></div>}
            {error && <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-rose-400/15 bg-rose-400/[0.05] px-3 py-2.5 text-small leading-5 text-rose-200"><span>{error}</span><span className="flex shrink-0 items-center gap-2">{canRetry && !streaming && <button type="button" onClick={() => void chat.retryLastMessage()} className="rounded-lg border border-rose-300/25 px-2.5 py-1 text-caption text-rose-100 transition hover:bg-rose-300/10">Try again</button>}<button onClick={() => setError('')} aria-label="Dismiss error"><X size={13} /></button></span></div>}
            {pendingApprovals.length > 0 && (
              <div className="mb-4 space-y-2" role="region" aria-label="Pending approval">
                <div className="flex gap-2 rounded-xl border border-amber-300/20 bg-amber-300/[0.05] px-3.5 py-2.5">
                  <LockKeyhole size={13} className="mt-0.5 shrink-0 text-amber-300" />
                  <div className="min-w-0 flex-1">
                    <p className="text-small font-medium text-amber-100/90">
                      Pentagon wants to {pendingApprovals.length === 1
                        ? `do this:`
                        : `do these ${pendingApprovals.length} things:`}
                    </p>
                    <ul className="mt-1 space-y-0.5">
                      {pendingApprovals.map((approval) => (
                        <li key={approval.id} className="font-mono text-[11px] text-amber-100/70">
                          {approval.label}
                          <span className="ml-2 text-amber-100/40">· {approval.tool_name}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {pendingApprovals.map((approval) => (
                    <span key={approval.id} className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => void dismissPendingApproval(approval, true)}
                        className="rounded-lg bg-amber-200/90 px-3 py-1.5 text-caption font-semibold text-black transition hover:bg-amber-100"
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => void dismissPendingApproval(approval, false)}
                        className="rounded-lg border border-white/[0.12] px-3 py-1.5 text-caption text-zinc-300 transition hover:bg-white/[0.06]"
                      >
                        Deny
                      </button>
                    </span>
                  ))}
                  {pendingApprovalsError && (
                    <p className="ml-auto text-micro text-amber-200/80">{pendingApprovalsError}</p>
                  )}
                </div>
              </div>
            )}
            {/*
              The token stream itself is deliberately not a live region: it fires
              many times a second and would drown a screen reader in fragments.
              This announces only the transitions that matter.
            */}
            <p role="status" aria-live="polite" className="sr-only">{conversationAnnouncement}</p>
            {/*
              Thread documents sit with the conversation rather than in the
              header, and only when this thread actually has some: a draft has
              nowhere to store them yet, and an empty thread has nothing to
              reference.
            */}
            {!isDraftThread && documents.length > 0 && <div className="mb-5 flex flex-wrap items-center gap-1.5">
              <span className="mr-0.5 text-micro font-medium uppercase tracking-[.15em] text-zinc-600">In this thread</span>
              {documents.map((doc) => <span key={doc.document_id} title={`${doc.filename} · ${doc.chunks_stored} indexed chunks`} className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-sky-300/10 bg-sky-300/[0.045] px-2 py-1.5 text-caption text-sky-100/80">
                <FileText size={11} className="shrink-0" />
                <span className="max-w-[220px] truncate">{doc.filename}</span>
                <span className="font-mono text-[10px] text-sky-100/40">{doc.chunks_stored}</span>
              </span>)}
            </div>}
            {messages.length ? <div className="space-y-8">
              {messages.map((message, index) => <MessageRow
                key={message.id}
                message={message}
                isStreaming={streaming && index === messages.length - 1}
                copied={copiedId === message.id}
                onCopy={() => void copyMessage(message)}
                onDecideCommand={(approved) => {
                  const pending = message.pendingCommand
                  if (pending) void chat.decideCommand(pending.request_id, approved)
                }}
                onApproveTools={(turnId, callIds) => void chat.decideAgentTools(turnId, callIds)}
                onDenyTools={(turnId) => void chat.denyAgentTools(turnId)}
                onAnswerQuestion={(turnId, text) => void chat.answerAgentQuestion(turnId, text)}
                commandTimeoutSeconds={commandSettings.approval_timeout_seconds}
                deciding={Boolean((message.pendingCommand && deciding === message.pendingCommand.request_id) || (message.turnId && deciding === message.turnId))}
              />)}
            </div> : (
              <div className="empty-state-enter flex flex-1 flex-col items-center justify-center py-10 text-center">
                <div className="relative mb-6 grid size-[88px] place-items-center">
                  <div className="absolute inset-0 rounded-full bg-emerald-400/[0.14] blur-2xl" />
                  <LogomarkBadge size={72} />
                </div>

                <p className="mb-2 text-caption font-semibold uppercase tracking-[.25em] text-emerald-300/80">
                  Intelligent Workspace
                </p>

                <h1 className="max-w-xl text-balance text-hero-fluid font-medium leading-[1.14] tracking-[-.04em] text-zinc-100">
                  {active
                    ? (userName ? `How can I help you today, ${userName}?` : 'How can I help you today?')
                    : (userName ? `Welcome back, ${userName}` : 'Welcome back')}
                </h1>

                <div className="mt-3.5 flex flex-wrap items-center justify-center gap-2 text-micro">
                  <span className="flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1 text-zinc-400">
                    <Sparkles size={11} className="text-emerald-400" /> Multi-Step Reasoning
                  </span>
                  <span className="flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1 text-zinc-400">
                    <Globe size={11} className="text-sky-400" /> Grounded Search
                  </span>
                  <span className="flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1 text-zinc-400">
                    <FileText size={11} className="text-purple-400" /> Rich Deliverables
                  </span>
                </div>

                {!active && (
                  <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
                    <button
                      onClick={startThread}
                      className="flex items-center gap-2 rounded-full bg-emerald-400 px-5 py-2.5 text-small font-semibold text-black transition hover:bg-emerald-300 hover:shadow-[0_4px_20px_rgba(16,185,129,0.3)]"
                    >
                      <Plus size={15} />
                      <span>Start a new thread</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setKeyNeeded(true)}
                      className="flex items-center gap-1.5 rounded-full border border-white/[0.1] bg-white/[0.04] px-4 py-2.5 text-small text-zinc-300 transition hover:border-emerald-500/30 hover:bg-white/[0.08] hover:text-white"
                    >
                      <Key size={13} className="text-emerald-400" />
                      <span>NVIDIA Key</span>
                    </button>
                  </div>
                )}

                {/* Quick Action Cards Grid */}
                <div className="mt-8 grid w-full max-w-2xl grid-cols-2 gap-3 max-sm:grid-cols-1">
                  {DASHBOARD_ACTIONS.map((card) => {
                    const Icon = card.icon
                    return (
                      <button
                        key={card.title}
                        type="button"
                        onClick={() => {
                          if (!active) startThread()
                          setDraft(card.prompt)
                        }}
                        className="group flex flex-col items-start rounded-2xl border border-white/[0.08] bg-white/[0.025] p-3.5 text-left transition duration-200 hover:-translate-y-0.5 hover:border-emerald-400/30 hover:bg-emerald-400/[0.04] hover:shadow-[0_8px_24px_rgba(0,0,0,0.5)]"
                      >
                        <div className="mb-2.5 flex w-full items-center justify-between">
                          <div className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-emerald-400 transition group-hover:border-emerald-400/30 group-hover:bg-emerald-400/10">
                            <Icon size={16} />
                          </div>
                          <span className="rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-zinc-400 group-hover:text-emerald-300">
                            {card.tag}
                          </span>
                        </div>
                        <div className="text-small font-semibold text-zinc-200 group-hover:text-white">
                          {card.title}
                        </div>
                        <div className="mt-1.5 flex items-center gap-1.5 text-micro text-emerald-400/80">
                          <Sparkles size={11} />
                          <span>{card.badge}</span>
                        </div>
                      </button>
                    )
                  })}
                </div>

                {/* Shortcut hints pill bar */}
                <div className="mt-7 flex flex-wrap items-center justify-center gap-3 text-caption text-zinc-500">
                  <span className="flex items-center gap-1.5">
                    <kbd className="rounded border border-white/[0.1] bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-zinc-300">⌘N</kbd>
                    <span>New thread</span>
                  </span>
                  <span>·</span>
                  <span className="flex items-center gap-1.5">
                    <kbd className="rounded border border-white/[0.1] bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-zinc-300">⌘K</kbd>
                    <span>Commands</span>
                  </span>
                  <span>·</span>
                  <span className="flex items-center gap-1.5">
                    <kbd className="rounded border border-white/[0.1] bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-zinc-300">⌘B</kbd>
                    <span>Sidebar</span>
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        <div
          className={`relative mx-auto w-full max-w-[980px] 2xl:max-w-[1140px] px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-2 sm:px-7 sm:pb-5 ${dragging ? 'after:pointer-events-none after:absolute after:inset-x-7 after:top-0 after:bottom-5 after:rounded-2xl after:border after:border-dashed after:border-emerald-300/60 after:bg-emerald-300/[0.04] after:content-["Drop_files_to_attach"] after:grid after:place-items-center after:text-body after:text-emerald-100' : ''}`}
          onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
          onDrop={(event) => { event.preventDefault(); setDragging(false); void acceptFiles(Array.from(event.dataTransfer.files)) }}
        >
          {/* Fade the last message into the composer instead of hard-cutting it. */}
          <div aria-hidden="true" className="pointer-events-none -mt-12 h-12 bg-gradient-to-t from-[#000000] via-[#000000]/70 to-transparent" />
          {media && <div className="mb-2 flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-3 py-2 text-micro text-zinc-300"><span className="text-emerald-200">{isVideo(media) ? <Video size={13} /> : <ImageIcon size={13} />}</span><span className="min-w-0 flex-1 truncate">{media.name}</span><span className="text-zinc-600">{isVideo(media) ? 'Video' : 'Image'}</span><button onClick={() => setMedia(null)} aria-label="Remove attachment" className="text-zinc-500 hover:text-white"><X size={13} /></button></div>}
          {queuedDocuments.length > 0 && <div className="mb-2 flex flex-wrap gap-1.5">{queuedDocuments.map((file, index) => <span key={`${file.name}-${index}`} className="panel-enter inline-flex max-w-full items-center gap-1.5 rounded-lg border border-sky-300/10 bg-sky-300/[0.045] px-2 py-1.5 text-caption text-sky-100/80"><FileText size={11} /><span className="max-w-[180px] truncate">{file.name}</span><span className="text-sky-100/40">queued</span><button onClick={() => setQueuedDocuments((items) => items.filter((_, current) => current !== index))} aria-label={`Remove ${file.name}`}><X size={11} /></button></span>)}</div>}
          <form onSubmit={(event) => void chat.handleSubmit(event)} className="rounded-2xl border border-white/[0.09] bg-[#0f0f0f] p-2 shadow-[0_20px_90px_rgba(0,0,0,.28)] transition-[border-color,box-shadow] duration-200 ease-out focus-within:border-emerald-300/25 focus-within:shadow-[0_0_0_3px_rgba(255,255,255,.045),0_20px_90px_rgba(0,0,0,.28)]">
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={chat.handleComposerKey} onFocus={() => setComposerFocused(true)} onBlur={() => setComposerFocused(false)} rows={2} disabled={!active || streaming || transcribing} placeholder={active ? 'Message Pentagon…' : 'Start a new thread to begin'} className="max-h-44 min-h-[55px] w-full resize-y bg-transparent px-3 py-2 text-body-lg leading-6 text-zinc-100 outline-none placeholder:text-zinc-600 disabled:cursor-not-allowed" aria-label="Write a message" />
            <div className="flex items-center justify-between gap-2 px-1 pb-0.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo,.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.csv,.tsv,.txt,.md,.markdown,.json,.yaml,.yml,.html,.htm,.xml,.rst,.py,.js,.ts,.tsx,.jsx,.sh,.sql,.log" multiple hidden onChange={(event) => void chat.handleAttachmentChange(event)} />
                <button type="button" onClick={() => fileInput.current?.click()} disabled={!active || streaming || uploading} className="flex min-h-9 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-micro text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-200 disabled:opacity-40" title="Attach an image, video, document, or spreadsheet"><Paperclip size={14} /><span className="max-sm:hidden">Attach</span></button>
                <button type="button" onClick={() => void chat.toggleRecording()} disabled={!active || streaming || transcribing} className={`grid size-8 place-items-center rounded-lg transition ${recording ? 'bg-rose-400/10 text-rose-300' : 'text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200'} disabled:opacity-40`} title={recording ? 'Stop recording' : 'Record a voice message - replies come back spoken'} aria-label={recording ? 'Stop recording' : 'Record a voice message'}>{recording ? <Square size={12} fill="currentColor" /> : <Mic size={14} />}</button>
                <button
                  type="button"
                  onClick={() => void handleToggleLocation()}
                  disabled={!active || locating}
                  className={`flex min-h-8 items-center gap-1.5 rounded-lg px-2.5 py-1 text-micro transition ${
                    userLocation
                      ? 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
                      : locating
                      ? 'bg-white/[0.06] text-zinc-300'
                      : 'text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200'
                  } disabled:opacity-40`}
                  title={
                    userLocation
                      ? `GPS Active: ${[userLocation.city, userLocation.country].filter(Boolean).join(', ') || `${userLocation.latitude.toFixed(2)}, ${userLocation.longitude.toFixed(2)}`} (Click to disable)`
                      : locating
                      ? 'Acquiring GPS location…'
                      : 'Enable GPS location for accurate local answers and nearby factors'
                  }
                  aria-label="Toggle GPS location"
                >
                  {locating ? (
                    <LoaderCircle size={13} className="animate-spin text-emerald-400" />
                  ) : (
                    <MapPin size={13} className={userLocation ? 'text-emerald-400 fill-emerald-400/20' : ''} />
                  )}
                  <span className="max-sm:hidden">
                    {locating
                      ? 'Locating…'
                      : userLocation
                      ? userLocation.city || 'GPS On'
                      : 'Location'}
                  </span>
                </button>
              </div>
              {streaming
                ? <button type="button" onClick={chat.stopStreaming} className="grid size-8 shrink-0 place-items-center rounded-xl border border-white/[0.1] bg-white/[0.06] text-zinc-200 transition-[background-color,transform] duration-200 ease-out hover:bg-white/[0.1] active:scale-95" aria-label="Stop generating" title="Stop generating"><Square size={13} fill="currentColor" /></button>
                : <button type="submit" disabled={!active || !selectedModel || transcribing || (!draft.trim() && !media)} className="grid size-8 shrink-0 place-items-center rounded-xl bg-emerald-300 text-[#000000] transition-[background-color,box-shadow,transform] duration-200 ease-out hover:-translate-y-px hover:bg-emerald-200 hover:shadow-[0_6px_18px_rgba(255,255,255,.12)] active:translate-y-0 active:scale-95 disabled:translate-y-0 disabled:scale-100 disabled:bg-white/[0.06] disabled:text-zinc-600 disabled:shadow-none" aria-label="Send message" title="Send message">{transcribing ? <LoaderCircle size={15} className="animate-spin" /> : <ArrowUp size={16} strokeWidth={2.4} />}</button>}
              <span className="sr-only">{queuedDocuments.length ? `${queuedDocuments.length} documents queued` : uploading ? 'Uploading document' : ''}</span>
            </div>
          </form>
          <div className="flex items-center justify-between gap-3 px-2 pt-2 text-caption text-zinc-600 max-sm:text-caption-xs">
            <span className="truncate">Drop files to upload · Markdown supported</span>
            {(transcribing || uploading) && (
              <span className="max-w-[50%] truncate text-right">{transcribing ? 'Transcribing…' : 'Uploading…'}</span>
            )}
          </div>
        </div>
      </section>)}
    </main>
    {paletteOpen ? (
      <Suspense fallback={null}>
        <CommandPalette
          onNewThread={startThread}
          onFocusSearch={focusSearch}
          onOpenSettings={() => setSettingsOpen(true)}
          onClose={() => setPaletteOpen(false)}
        />
      </Suspense>
    ) : null}
    {settingsOpen ? (
      <Suspense fallback={null}>
        <SettingsDialog
          initialTab={settingsTab}
          initialSection={settingsSection}
          userId={userId}
          models={models}
          serverDefaultModel={defaultModel}
          documents={documents}
          threads={threads}
          threadCount={threads.length}
          onRenameThread={(id, title) => void renameThread(id, title)}
          onDeleteThread={(id) => void deleteThread(id)}
          onClose={() => {
            setSettingsOpen(false)
            setSettingsSection(undefined)
          }}
          onKeySaved={() => void refreshModels()}
          commandSettings={commandSettings}
          onCommandSettingsChange={(enabled) => setCommandSettings((current) => ({ ...current, enabled }))}
          autonomySettings={autonomySettings}
          onAutonomySettingChange={changeAutonomySetting}
          onAutonomyPresetChange={changeAutonomyPreset}
          onDocumentDeleted={(documentId) =>
            setDocuments((current) => current.filter((item) => item.document_id !== documentId))
          }
        />
      </Suspense>
    ) : null}
  </div>
}

function MessageRowImpl({ message, isStreaming = false, copied = false, onCopy, onDecideCommand, onApproveTools, onDenyTools, onAnswerQuestion, commandTimeoutSeconds = 300, deciding = false }: {
  message: ChatMessage
  isStreaming?: boolean
  copied?: boolean
  onCopy?: () => void
  onDecideCommand?: (approved: boolean) => void
  onApproveTools?: (turnId: string, callIds: string[]) => void
  onDenyTools?: (turnId: string) => void
  onAnswerQuestion?: (turnId: string, text: string) => void
  commandTimeoutSeconds?: number
  deciding?: boolean
}) {
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  const currentUserName = prefs.userName.trim() || 'You'
  const currentAvatarTheme = AVATAR_THEMES[prefs.userAvatarColor] ?? AVATAR_THEMES.emerald
  const userInitials =
    (currentUserName === 'You' ? 'U' : currentUserName)
      .split(' ')
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0].toUpperCase())
      .join('') || 'U'
  const user = message.role === 'user'
  return <article data-assistant-message={user ? undefined : ''} className={`message-enter group flex w-full gap-3 ${user ? 'justify-end' : 'justify-start'}`}>
    {!user && <div className="mt-0.5 grid size-7 shrink-0 place-items-center"><Logomark size={20} /></div>}
    <div className={`min-w-0 ${user ? 'max-w-[78%]' : 'w-full max-w-[calc(100%-40px)]'}`}>
      <div className={`mb-2 flex items-center gap-2 text-micro ${user ? 'justify-end pr-1 text-zinc-500' : 'text-zinc-500'}`}><span className="font-medium text-zinc-300">{user ? currentUserName : 'Pentagon'}</span></div>
      {user ? <div className="rounded-2xl rounded-tr-md border border-white/[0.07] bg-[#171717] px-4 py-3 text-body-lg leading-6 text-zinc-100">
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
        {message.attachmentName && <div className="mt-2 flex items-center gap-1.5 text-caption text-zinc-500"><Paperclip size={11} />{message.attachmentName}</div>}
      </div> : <div className="min-w-0 pt-0.5">
        <AgentActivity
          message={message}
          busy={deciding}
          onApprove={(turnId, callIds) => onApproveTools?.(turnId, callIds)}
          onDeny={(turnId) => onDenyTools?.(turnId)}
          onAnswer={(turnId, text) => onAnswerQuestion?.(turnId, text)}
        />
        {message.content || (message.generatedFiles && message.generatedFiles.length > 0) ? (
          <div className={isStreaming ? 'streaming-answer' : undefined}>
            <AssistantDetails message={message} />
          </div>
        ) : (!message.agentSteps?.length ? (
          <ThinkingIndicator model={message.model_used} />
        ) : null)}
      {/* Above the answer: while a command is pending there is nothing to read
          yet, so the prompt has to be the thing the eye lands on. */}
      {message.pendingCommand && onDecideCommand ? <CommandApproval
        pending={message.pendingCommand}
        timeoutSeconds={commandTimeoutSeconds}
        busy={deciding}
        onDecide={onDecideCommand}
      /> : null}
      {message.commandRuns?.length ? <CommandLog runs={message.commandRuns} /> : null}
      {!user && message.content ? <div className="mt-2 flex items-center gap-2 opacity-0 transition-opacity duration-200 focus-within:opacity-100 group-hover:opacity-100 max-sm:opacity-100">
        <button type="button" onClick={onCopy} className="flex min-h-9 items-center gap-1.5 rounded-lg px-2 py-1 text-micro text-zinc-600 transition hover:bg-white/[0.05] hover:text-zinc-300" aria-label="Copy answer">{copied ? <Check size={11} className="text-emerald-300" /> : <Copy size={11} />}{copied ? 'Copied' : 'Copy'}</button>
      </div> : null}
      </div>}
    </div>
    {user && (
      <div
        className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border ${currentAvatarTheme.border} ${currentAvatarTheme.bg} text-[11px] font-semibold ${currentAvatarTheme.text}`}
      >
        {userInitials}
      </div>
    )}
  </article>
}

// Memoised so a streaming token only re-renders the message being written.
// Without this, every token re-parsed the markdown of every message in the
// thread, which is what made long answers stutter. The comparator ignores
// onCopy because it is a fresh closure each render, yet it closes over exactly
// the `message` the other three props already pin down.
const MessageRow = memo(MessageRowImpl, (previous, next) =>
  previous.message === next.message &&
  previous.isStreaming === next.isStreaming &&
  previous.copied === next.copied &&
  previous.deciding === next.deciding
)

export default App

