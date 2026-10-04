import { memo, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import { ArrowUp, Check, ChevronDown, Copy, FileText, Image as ImageIcon, LoaderCircle, LockKeyhole, Menu, Mic, Paperclip, Plus, Square, Video, X } from 'lucide-react'
import { apiRequest, ApiError, apiUrl, getLocalUserId, pcmToWavUrl } from './api'
import { AssistantDetails } from './components/MessageContent'
import { Sidebar } from './components/Sidebar'
import { Logomark, LogomarkBadge } from './components/Logomark'
import { ThinkingIndicator } from './components/ThinkingIndicator'
import { AmbientLayer } from './components/AmbientLayer'
import { CommandPalette } from './components/CommandPalette'
import { SettingsDialog } from './components/SettingsDialog'
import { setAmbientSignal } from './lib/ambient'
import { getPreferences, toggleSidebarCollapsed } from './lib/preferences'
import type { ChatMessage, Conversation, DocumentInfo, ExecutionTrace, ModelInfo, SourcesUsed } from './types'

type ConversationDetail = Conversation & { messages: ChatMessage[]; summary_at_switch: string | null }
type TranscriptInfo = { durationMs: number; provider: string }
type Validation = 'idle' | 'checking' | 'valid' | 'invalid'

/** How often streamed text is committed to the message list. Each commit re-parses
    the answer through react-markdown, so this trades a little latency for a
    steady, inexpensive update rate. */
const STREAM_FLUSH_MS = 45

function titleFor(message: string) {
  const normalized = message.trim().replace(/\s+/g, ' ')
  return normalized.length > 54 ? `${normalized.slice(0, 51)}…` : normalized || 'New thread'
}

function decodeAudio(value: string): Uint8Array {
  const raw = atob(value)
  const bytes = new Uint8Array(raw.length)
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index)
  return bytes
}

function isDocument(file: File) {
  return /\.(pdf|docx|txt)$/i.test(file.name)
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
function chooseDefaultModel(available: ModelInfo[], preferred: string, serverDefault: string): string {
  if (preferred && available.some((model) => model.id === preferred)) return preferred
  if (serverDefault && available.some((model) => model.id === serverDefault)) return serverDefault
  return available[0]?.id || ''
}

function App() {
  const [userId] = useState(getLocalUserId)
  const [booting, setBooting] = useState(true)
  const [keyNeeded, setKeyNeeded] = useState(false)
  const [keyValue, setKeyValue] = useState('')
  const [keyValidation, setKeyValidation] = useState<Validation>('idle')
  const [keyValidationMessage, setKeyValidationMessage] = useState('Enter a key to validate it with NVIDIA.')
  const [savingKey, setSavingKey] = useState(false)
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
  const fileInput = useRef<HTMLInputElement>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const streamAbort = useRef<AbortController | null>(null)
  const currentAssistantIndex = useRef(0)
  const conversationViewport = useRef<HTMLDivElement>(null)
  const followConversation = useRef(true)
  const openThreadToken = useRef(0)
  const scrollFrame = useRef<number | null>(null)

  const activeModel = models.find((item) => item.id === selectedModel)
  const activeId = active?.id || null
  const sidebarThreads = active && 'isDraft' in active && active.isDraft ? [active as Conversation, ...threads] : threads
  const isDraftThread = Boolean(active && 'isDraft' in active && active.isDraft)
  const conversationAnnouncement = useMemo(() => {
    if (transcribing) return 'Transcribing your recording.'
    if (uploading) return 'Uploading a document.'
    if (switching) return 'Switching model.'
    if (streaming) return stoppedReply ? 'Stopping the reply.' : 'Pentagon is replying.'
    const last = messages[messages.length - 1]
    if (last?.role !== 'assistant' || !last.content) return ''
    return stoppedReply ? 'Reply stopped.' : 'Reply finished.'
  }, [streaming, transcribing, uploading, switching, messages, stoppedReply])

  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      setBooting(true)
      let preferredModel = ''
      let list: Conversation[] = []
      try {
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
      } catch (cause) {
        if (cancelled) return
        if (cause instanceof ApiError && cause.status === 404) {
          // 404 on the thread detail could also mean this browser has no stored
          // threads yet. Only gate on the key when no default model is configured.
          if (list.length === 0) setKeyNeeded(!preferredModel)
        } else {
          setError(cause instanceof Error ? cause.message : 'Could not connect to the Pentagon backend.')
        }
      } finally {
        if (!cancelled) setBooting(false)
      }
    }
    void hydrate()
    return () => { cancelled = true }
  }, [userId])

  useEffect(() => {
    if (!keyValue.trim()) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const result = await apiRequest<{ valid: boolean; reason?: string }>('/api/keys/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: keyValue }),
          signal: controller.signal,
        })
        setKeyValidation(result.valid ? 'valid' : 'invalid')
        setKeyValidationMessage(result.valid ? 'Key verified and ready to save.' : result.reason || 'NVIDIA did not accept this key.')
      } catch (cause) {
        if (controller.signal.aborted) return
        setKeyValidation('invalid')
        setKeyValidationMessage(cause instanceof Error ? cause.message : 'Key validation failed.')
      }
    }, 500)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [keyValue])

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
  useEffect(() => () => streamAbort.current?.abort(), [])

  // The ambient layer reacts to what the app is actually doing.
  useEffect(() => {
    const lastMessage = messages[messages.length - 1]
    setAmbientSignal('streaming', streaming && Boolean(lastMessage?.content))
    setAmbientSignal('thinking', streaming || transcribing || uploading || switching)
    setAmbientSignal('error', Boolean(error))
    setAmbientSignal('focus', composerFocused)
    setAmbientSignal('offline', !navigator.onLine)
  }, [streaming, transcribing, uploading, switching, error, messages, composerFocused])

  useEffect(() => {
    const sync = () => setAmbientSignal('offline', !navigator.onLine)
    window.addEventListener('online', sync)
    window.addEventListener('offline', sync)
    return () => {
      window.removeEventListener('online', sync)
      window.removeEventListener('offline', sync)
    }
  }, [])

  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((value) => !value)
        return
      }
      if (event.key === 'Escape') {
        setPaletteOpen(false)
        return
      }
      const target = event.target as HTMLElement | null
      const typing = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA'
      if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
        event.preventDefault()
        jumpToMessage(event.key === 'ArrowDown' ? 1 : -1)
        return
      }
      if (event.key === '/' && !typing && active) {
        event.preventDefault()
        document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Write a message"]')?.focus()
        return
      }
      if (meta && event.shiftKey && event.key.toLowerCase() === 'o') {
        event.preventDefault()
        startThread()
        return
      }
      // ⌘B / Ctrl+B folds the sidebar away to an icon rail. Ignored on a phone,
      // where the sidebar is already a full-width drawer.
      if (meta && !event.shiftKey && event.key.toLowerCase() === 'b') {
        if (window.matchMedia('(min-width: 768px)').matches) {
          event.preventDefault()
          toggleSidebarCollapsed()
        }
        return
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
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

  async function saveKey(event: FormEvent) {
    event.preventDefault()
    if (keyValidation !== 'valid' || savingKey) return
    setSavingKey(true)
    setError('')
    try {
      await apiRequest('/api/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, api_key: keyValue }),
      })
      setKeyValue('')
      setKeyNeeded(false)
      setBooting(true)
      window.location.reload()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not store the NVIDIA key.')
    } finally {
      setSavingKey(false)
    }
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
    const result = await apiRequest<DocumentInfo[]>(`/api/documents?user_id=${encodeURIComponent(userId)}&conversation_id=${encodeURIComponent(conversationId)}`)
    setDocuments(result)
    return result
  }

  async function uploadDocument(file: File, conversationId: string) {
    const form = new FormData()
    form.set('user_id', userId)
    form.set('conversation_id', conversationId)
    form.set('file', file)
    const result = await apiRequest<DocumentInfo>('/api/documents/upload', { method: 'POST', body: form })
    await loadDocuments(conversationId)
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
      else setError(`${file.name} is not a supported image, video, PDF, DOCX, or TXT file.`)
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

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault()
    const typed = draft.trim()
    if (streaming || transcribing || uploading || !active || !selectedModel || (!typed && !media)) return
    const question = typed || (media && isVideo(media) ? 'Describe what happens in this video with timestamps.' : 'Describe what is in this image.')
    const pendingDocs = [...queuedDocuments]
    const mediaForMessage = media
    const modelForMessage = selectedModel
    followConversation.current = true
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(), role: 'user', content: question, model_used: modelForMessage,
      attachmentName: mediaForMessage?.name,
    }
    const assistantId = crypto.randomUUID()
    setError('')
    setNotice('')
    setStreaming(true)
    setStoppedReply(false)
    setDraft('')
    setTranscriptInfo(null)
    // The composer is emptied above, but nothing is committed to the thread
    // until the uploads finish. Without this the typed question was lost for
    // good whenever an attachment failed: it was gone from the composer and
    // never appeared in the conversation.
    let messageShown = false
    try {
      const thread = await createRemoteThread(question)
      let uploaded = 0
      for (const file of pendingDocs) {
        await uploadDocument(file, thread.id)
        uploaded += 1
        // Trim as we go, so a failure part-way through leaves exactly the
        // files that never made it, not all of them again.
        setQueuedDocuments((items) => items.slice(uploaded))
      }
      setQueuedDocuments([])
      const assistant: ChatMessage = { id: assistantId, role: 'assistant', content: '', model_used: modelForMessage }
      setMessages((current) => [...current, userMessage, assistant])
      messageShown = true
      const form = new FormData()
      form.set('user_id', userId)
      form.set('conversation_id', thread.id)
      form.set('model', modelForMessage)
      form.set('message', question)
      // Web search is not a user toggle: omitting the field lets the backend
      // router decide when a question actually needs live results.
      if (transcriptInfo) form.set('respond_with_audio', 'true')
      if (mediaForMessage) form.set(isVideo(mediaForMessage) ? 'video' : 'image', mediaForMessage)
      if (transcriptInfo) {
        form.set('transcription_duration_ms', String(transcriptInfo.durationMs))
        form.set('transcription_provider', transcriptInfo.provider)
      }
      setMedia(null)
      await streamResponse(form, assistantId)
      const list = await refreshThreads()
      const refreshed = list.find((item) => item.id === thread.id)
      if (refreshed) setActive((current) => current && current.id === refreshed.id ? { ...current, title: refreshed.title, updated_at: refreshed.updated_at } : current)
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        setNotice('Stopped. The partial answer above was kept.')
        if (messageShown) setMessages((current) => current.map((item) => item.id === assistantId && !item.content ? { ...item, content: 'Stopped before an answer was produced.' } : item))
      } else {
        setError(cause instanceof Error ? cause.message : 'The chat request failed.')
        if (messageShown) {
          setMessages((current) => current.map((item) => item.id === assistantId && !item.content ? { ...item, content: 'I could not complete that request.' } : item))
        } else {
          // Nothing reached the thread -- creating it or uploading an
          // attachment failed first -- so the question goes back to the
          // composer instead of vanishing along with the cleared draft.
          setDraft((current) => (current.trim() ? current : question))
        }
      }
    } finally { setStreaming(false) }
  }

  function stopStreaming() {
    setStoppedReply(true)
    streamAbort.current?.abort()
  }

  function focusSearch() {
    document.querySelector<HTMLInputElement>('input[aria-label="Search conversations"]')?.focus()
  }

  async function streamResponse(form: FormData, assistantId: string) {
    const controller = new AbortController()
    streamAbort.current = controller
    const response = await fetch(apiUrl('/api/chat'), {
      method: 'POST',
      body: form,
      headers: { Accept: 'text/event-stream' },
      signal: controller.signal,
    })
    if (!response.ok) {
      let message = `Chat request failed (${response.status})`
      try { message = (await response.json() as { detail?: string }).detail || message } catch { /* Keep status fallback. */ }
      throw new Error(message)
    }
    if (!response.body) throw new Error('The backend did not return a stream.')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let pending = ''
    let audioChunks: Uint8Array[] = []
    let sampleRate = 22050
    let channels = 1
    let bufferedText = ''
    let flushTimer: number | null = null
    let lastFlushAt = 0
    const update = (changes: Partial<ChatMessage>) => setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, ...changes } : item))
    const flushText = () => {
      if (flushTimer !== null) {
        window.clearTimeout(flushTimer)
        flushTimer = null
      }
      lastFlushAt = performance.now()
      if (!bufferedText) return
      const content = bufferedText
      bufferedText = ''
      setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, content: item.content + content } : item))
    }
    // Every flush re-parses the whole answer through react-markdown, so the
    // cost of a flush grows with the answer. Flushing on each animation frame
    // therefore produced an uneven cadence -- fine at first, then visibly
    // stuttering as the response got longer. A fixed window keeps the text
    // advancing steadily and cuts the number of parses to roughly a third.
    const queueText = (content: string) => {
      bufferedText += content
      if (flushTimer !== null) return
      const wait = Math.max(0, STREAM_FLUSH_MS - (performance.now() - lastFlushAt))
      flushTimer = window.setTimeout(flushText, wait)
    }
    const dispatch = (block: string) => {
      const lines = block.split('\n')
      const eventName = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
      const raw = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
      if (!raw) return
      let payload: Record<string, unknown>
      try { payload = JSON.parse(raw) as Record<string, unknown> } catch { return }
      if (eventName === 'token' && typeof payload.content === 'string') {
        queueText(payload.content)
      } else if (eventName === 'metadata') {
        update({
          sources_used: payload.sources_used as SourcesUsed,
          execution_trace: payload.execution_trace as ExecutionTrace,
        })
      } else if (eventName === 'audio_chunk' && typeof payload.content === 'string') {
        audioChunks.push(decodeAudio(payload.content))
        if (typeof payload.sample_rate_hz === 'number') sampleRate = payload.sample_rate_hz
        if (typeof payload.channels === 'number') channels = payload.channels
      } else if (eventName === 'audio_end') {
        if (typeof payload.sample_rate_hz === 'number') sampleRate = payload.sample_rate_hz
        if (typeof payload.channels === 'number') channels = payload.channels
        const audioUrl = pcmToWavUrl(audioChunks, sampleRate, channels)
        if (audioUrl) update({ audioUrl })
        audioChunks = []
      } else if (eventName === 'audio_error') {
        setError(String(payload.message || 'The text response is ready, but speech synthesis failed.'))
      } else if (eventName === 'error') {
        throw new Error(String(payload.message || 'The model request failed.'))
      }
    }
    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        if (streamAbort.current?.signal.aborted) break
        pending += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        let boundary = pending.indexOf('\n\n')
        while (boundary >= 0) {
          dispatch(pending.slice(0, boundary))
          pending = pending.slice(boundary + 2)
          boundary = pending.indexOf('\n\n')
        }
      }
      pending += decoder.decode()
      if (pending.trim()) dispatch(pending)
    } finally {
      flushText()
      streamAbort.current = null
    }
  }

  async function toggleRecording() {
    if (recording) { recorder.current?.stop(); setRecording(false); return }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Audio recording is not available in this browser.')
      return
    }
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const chunks: Blob[] = []
      const mediaRecorder = new MediaRecorder(stream)
      recorder.current = mediaRecorder
      mediaRecorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
        recorder.current = null
        const mime = mediaRecorder.mimeType || 'audio/webm'
        const ext = mime.includes('wav') ? 'wav' : mime.includes('mpeg') ? 'mp3' : 'webm'
        void transcribeRecording(new Blob(chunks, { type: mime }), ext)
      }
      mediaRecorder.start()
      setRecording(true)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Microphone permission was denied.') }
  }

  async function transcribeRecording(blob: Blob, extension: string) {
    setTranscribing(true)
    setNotice('Transcribing audio…')
    const form = new FormData()
    form.set('user_id', userId)
    form.set('file', blob, `recording.${extension}`)
    try {
      const result = await apiRequest<{ text: string; execution_trace?: { transcription?: { duration_ms?: number; provider?: string } } }>('/api/voice/transcribe', { method: 'POST', body: form })
      if (!result.text.trim()) {
        setNotice('No speech was detected. Record another clip or type a message.')
        return
      }
      setDraft((current) => current ? `${current.trimEnd()} ${result.text.trim()}` : result.text.trim())
      const trace = result.execution_trace?.transcription
      setTranscriptInfo({ durationMs: trace?.duration_ms || 0, provider: trace?.provider || 'unspecified' })
      setNotice('Transcript added to the composer. Review or edit it before sending.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not transcribe this recording.') }
    finally { setTranscribing(false) }
  }

  async function handleAttachmentChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    await acceptFiles(files)
  }

  async function handleSubmit(event: FormEvent) {
    await sendMessage(event)
  }

  function handleComposerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  if (booting) return <div className="grid h-full min-h-dvh place-items-center bg-[#000000] text-sm text-zinc-500"><div className="flex items-center gap-3"><LogomarkBadge size={32} /><span>Connecting to Pentagon…</span></div></div>

  if (keyNeeded) return <KeyGate
    value={keyValue}
    validation={keyValidation}
    validationMessage={keyValidationMessage}
    saving={savingKey}
    error={error}
    onChange={(value) => {
      setKeyValue(value)
      setKeyValidation(value.trim() ? 'checking' : 'idle')
      setKeyValidationMessage(value.trim() ? 'Checking the key with NVIDIA…' : 'Enter a key to validate it with NVIDIA.')
      setError('')
    }}
    onSubmit={(event) => void saveKey(event)}
  />

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
      onOpenPalette={() => {
        setPaletteOpen(true)
        setSidebarOpen(false)
      }}
      onOpenSettings={() => {
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
          <div className="flex min-w-0 items-center gap-2 rounded-lg border border-white/[0.12] bg-black px-3 py-2">
            <Logomark size={16} />
            {/* Native <select>: the popup is drawn by the OS, so the options carry
                explicit black/white rather than inheriting the panel's greys. */}
            <select aria-label="Choose model" value={selectedModel} disabled={!models.length || switching || streaming} onChange={(event) => void switchModel(event.target.value)} className="h-7 max-w-[min(58vw,360px)] min-w-0 appearance-none bg-black text-small font-medium text-white outline-none disabled:text-zinc-500 sm:max-w-[min(38vw,360px)] lg:max-w-[min(34vw,360px)]">
              {!models.length && <option value="" className="bg-black text-white">No models available</option>}
              {models.map((model) => <option value={model.id} key={model.id} className="bg-black text-white">{model.id}{model.supports_vision ? ' · Vision' : ''}</option>)}
            </select>
            <ChevronDown size={12} className="shrink-0 text-zinc-400" />
          </div>
          
          {activeModel?.supports_vision && <span className="hidden items-center gap-1.5 rounded-full border border-violet-300/15 bg-violet-300/[0.06] px-2.5 py-1.5 text-micro text-violet-200 md:inline-flex"><ImageIcon size={11} />Vision ready</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2 max-sm:gap-1.5">
          <button onClick={startThread} className="grid size-8 place-items-center rounded-lg text-zinc-500 transition hover:bg-white/[0.06] hover:text-white md:hidden" title="New thread"><Plus size={16} /></button>
        </div>
      </header>

      <section className="relative flex min-h-0 flex-1 flex-col">
        {(!atBottom && messages.length > 0) ? <button type="button" onClick={jumpToLatest} className="panel-enter absolute bottom-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-white/[0.1] bg-[#0f0f0f]/95 px-3 py-1.5 text-micro text-zinc-300 shadow-[0_10px_30px_rgba(0,0,0,.45)] backdrop-blur transition hover:border-emerald-300/30 hover:text-zinc-100">
          <ChevronDown size={12} className="rotate-180" />Jump to latest
        </button> : null}
        <div ref={conversationViewport} onScroll={handleConversationScroll} className="flex min-h-0 flex-1 flex-col overflow-y-auto" aria-label="Conversation" role="log" aria-live="off">
          <div className="mx-auto flex w-full max-w-[850px] flex-1 flex-col px-4 pb-5 pt-5 sm:px-7 sm:pt-8">
            {notice && <div role="status" className="mb-4 flex items-center justify-between rounded-lg border border-emerald-300/10 bg-emerald-300/[0.04] px-3 py-2 text-small text-emerald-100/80"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss notice"><X size={13} /></button></div>}
            {error && <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-rose-400/15 bg-rose-400/[0.05] px-3 py-2.5 text-small leading-5 text-rose-200"><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error"><X size={13} /></button></div>}
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
              {messages.map((message, index) => <MessageRow key={message.id} message={message} isStreaming={streaming && index === messages.length - 1} copied={copiedId === message.id} onCopy={() => void copyMessage(message)} />)}
            </div> : <div className="empty-state-enter flex flex-1 flex-col items-center justify-center py-16 text-center">
              <div className="relative mb-7 grid size-[66px] place-items-center"><Logomark size={60} /><span className="absolute -right-1 -top-1 size-2 rounded-full bg-white/70" /></div>
              <p className="mb-3 text-caption font-medium uppercase tracking-[.23em] text-emerald-200/70">A focused place to think</p>
              <h1 className="max-w-xl text-balance text-hero-fluid font-medium leading-[1.12] tracking-[-.045em] text-zinc-100">{active ? 'What should we explore?' : 'A clear space for your next idea.'}</h1>
              <p className="mt-4 max-w-md text-body leading-6 text-zinc-500">Bring a question, a document, or a moment from a video. Pentagon will show the sources and work behind each reply.</p>
              {!active && <button onClick={startThread} className="mt-7 flex items-center gap-2 rounded-full bg-emerald-300 px-4 py-2.5 text-small font-semibold text-[#000000] transition hover:bg-emerald-200"><Plus size={14} />Start a new thread</button>}
              {active && <div className="mt-8 grid w-full max-w-lg grid-cols-2 gap-2.5 max-sm:grid-cols-1">
                {['Summarize the key points in my documents', 'Explain this code and show an example', 'Compare the main ideas in this topic', 'Describe what happens in an attached video'].map((suggestion) => <button key={suggestion} onClick={() => setDraft(suggestion)} className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3.5 py-3 text-left text-micro text-zinc-400 transition hover:border-emerald-300/20 hover:bg-emerald-300/[0.04] hover:text-zinc-200">{suggestion}</button>)}
              </div>}
            </div>}
          </div>
        </div>

        <div
          className={`relative mx-auto w-full max-w-[850px] px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-2 sm:px-7 sm:pb-5 ${dragging ? 'after:pointer-events-none after:absolute after:inset-x-7 after:top-0 after:bottom-5 after:rounded-2xl after:border after:border-dashed after:border-emerald-300/60 after:bg-emerald-300/[0.04] after:content-["Drop_files_to_attach"] after:grid after:place-items-center after:text-body after:text-emerald-100' : ''}`}
          onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
          onDrop={(event) => { event.preventDefault(); setDragging(false); void acceptFiles(Array.from(event.dataTransfer.files)) }}
        >
          {/* Fade the last message into the composer instead of hard-cutting it. */}
          <div aria-hidden="true" className="pointer-events-none -mt-12 h-12 bg-gradient-to-t from-[#000000] via-[#000000]/70 to-transparent" />
          {media && <div className="mb-2 flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-3 py-2 text-micro text-zinc-300"><span className="text-emerald-200">{isVideo(media) ? <Video size={13} /> : <ImageIcon size={13} />}</span><span className="min-w-0 flex-1 truncate">{media.name}</span><span className="text-zinc-600">{isVideo(media) ? 'Video' : 'Image'}</span><button onClick={() => setMedia(null)} aria-label="Remove attachment" className="text-zinc-500 hover:text-white"><X size={13} /></button></div>}
          {queuedDocuments.length > 0 && <div className="mb-2 flex flex-wrap gap-1.5">{queuedDocuments.map((file, index) => <span key={`${file.name}-${index}`} className="panel-enter inline-flex max-w-full items-center gap-1.5 rounded-lg border border-sky-300/10 bg-sky-300/[0.045] px-2 py-1.5 text-caption text-sky-100/80"><FileText size={11} /><span className="max-w-[180px] truncate">{file.name}</span><span className="text-sky-100/40">queued</span><button onClick={() => setQueuedDocuments((items) => items.filter((_, current) => current !== index))} aria-label={`Remove ${file.name}`}><X size={11} /></button></span>)}</div>}
          <form onSubmit={(event) => void handleSubmit(event)} className="rounded-2xl border border-white/[0.09] bg-[#0f0f0f] p-2 shadow-[0_20px_90px_rgba(0,0,0,.28)] transition-[border-color,box-shadow] duration-200 ease-out focus-within:border-emerald-300/25 focus-within:shadow-[0_0_0_3px_rgba(255,255,255,.045),0_20px_90px_rgba(0,0,0,.28)]">
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleComposerKey} onFocus={() => setComposerFocused(true)} onBlur={() => setComposerFocused(false)} rows={2} disabled={!active || streaming || transcribing} placeholder={active ? 'Message Pentagon…' : 'Start a new thread to begin'} className="max-h-44 min-h-[55px] w-full resize-y bg-transparent px-3 py-2 text-body-lg leading-6 text-zinc-100 outline-none placeholder:text-zinc-600 disabled:cursor-not-allowed" aria-label="Write a message" />
            <div className="flex items-center justify-between gap-2 px-1 pb-0.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo,.pdf,.docx,.txt" multiple hidden onChange={(event) => void handleAttachmentChange(event)} />
                <button type="button" onClick={() => fileInput.current?.click()} disabled={!active || streaming || uploading} className="flex min-h-9 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-micro text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200 disabled:opacity-40" title="Attach an image, video, or document"><Paperclip size={13} /><span className="max-sm:hidden">Attach</span></button>
                <button type="button" onClick={() => void toggleRecording()} disabled={!active || streaming || transcribing} className={`grid size-8 place-items-center rounded-lg transition ${recording ? 'bg-rose-400/10 text-rose-300' : 'text-zinc-500 hover:bg-white/[0.06] hover:text-zinc-200'} disabled:opacity-40`} title={recording ? 'Stop recording' : 'Record a voice message - replies come back spoken'} aria-label={recording ? 'Stop recording' : 'Record a voice message'}>{recording ? <Square size={12} fill="currentColor" /> : <Mic size={14} />}</button>
              </div>
              {streaming
                ? <button type="button" onClick={stopStreaming} className="grid size-8 shrink-0 place-items-center rounded-xl border border-white/[0.1] bg-white/[0.06] text-zinc-200 transition-[background-color,transform] duration-200 ease-out hover:bg-white/[0.1] active:scale-95" aria-label="Stop generating" title="Stop generating"><Square size={13} fill="currentColor" /></button>
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
      </section>
    </main>
    {paletteOpen ? <CommandPalette
      onNewThread={startThread}
      onFocusSearch={focusSearch}
      onOpenSettings={() => setSettingsOpen(true)}
      onClose={() => setPaletteOpen(false)}
    /> : null}
    {settingsOpen ? (
      <SettingsDialog
        userId={userId}
        models={models}
        serverDefaultModel={defaultModel}
        documents={documents}
        threads={threads}
        threadCount={threads.length}
        onRenameThread={(id, title) => void renameThread(id, title)}
        onDeleteThread={(id) => void deleteThread(id)}
        onClose={() => setSettingsOpen(false)}
        onKeySaved={() => void refreshModels()}
        onDocumentDeleted={(documentId) =>
          setDocuments((current) => current.filter((item) => item.document_id !== documentId))
        }
      />
    ) : null}
  </div>
}

function MessageRowImpl({ message, isStreaming = false, copied = false, onCopy }: { message: ChatMessage; isStreaming?: boolean; copied?: boolean; onCopy?: () => void }) {
  const user = message.role === 'user'
  return <article data-assistant-message={user ? undefined : ''} className={`message-enter group flex w-full gap-3 ${user ? 'justify-end' : 'justify-start'}`}>
    {!user && <div className="mt-0.5 grid size-7 shrink-0 place-items-center"><Logomark size={20} /></div>}
    <div className={`min-w-0 ${user ? 'max-w-[78%]' : 'w-full max-w-[calc(100%-40px)]'}`}>
      <div className={`mb-2 flex items-center gap-2 text-micro ${user ? 'justify-end pr-1 text-zinc-500' : 'text-zinc-500'}`}><span className="font-medium text-zinc-300">{user ? 'You' : 'Pentagon'}</span></div>
      {user ? <div className="rounded-2xl rounded-tr-md border border-white/[0.07] bg-[#171717] px-4 py-3 text-body-lg leading-6 text-zinc-100">
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
        {message.attachmentName && <div className="mt-2 flex items-center gap-1.5 text-caption text-zinc-500"><Paperclip size={11} />{message.attachmentName}</div>}
      </div> : <div className="min-w-0 pt-0.5">
        {message.content ? <div className={isStreaming ? 'streaming-answer' : undefined}><AssistantDetails message={message} /></div> : <ThinkingIndicator model={message.model_used} />}
      {!user && message.content ? <div className="mt-2 flex items-center gap-2 opacity-0 transition-opacity duration-200 focus-within:opacity-100 group-hover:opacity-100 max-sm:opacity-100">
        <button type="button" onClick={onCopy} className="flex min-h-9 items-center gap-1.5 rounded-lg px-2 py-1 text-micro text-zinc-600 transition hover:bg-white/[0.05] hover:text-zinc-300" aria-label="Copy answer">{copied ? <Check size={11} className="text-emerald-300" /> : <Copy size={11} />}{copied ? 'Copied' : 'Copy'}</button>
      </div> : null}
      </div>}
    </div>
    {user && <div className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border border-white/[0.08] bg-white/[0.04] text-caption text-zinc-400">Y</div>}
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
  previous.copied === next.copied
)

function KeyGate({ value, validation, validationMessage, saving, error, onChange, onSubmit }: {
  value: string
  validation: Validation
  validationMessage: string
  saving: boolean
  error: string
  onChange: (value: string) => void
  onSubmit: (event: FormEvent) => void
}) {
  const tone = validation === 'valid' ? 'text-emerald-300' : validation === 'invalid' ? 'text-rose-300' : validation === 'checking' ? 'text-amber-200' : 'text-zinc-500'
  return <main className="relative grid min-h-screen place-items-center overflow-hidden bg-[#000000] px-5 py-10 text-zinc-100">
    <div className="pointer-events-none absolute left-1/2 top-0 size-[500px] -translate-x-1/2 rounded-full bg-emerald-300/[0.04] blur-[100px]" />
    <section className="relative w-full max-w-[440px] rounded-[24px] border border-white/[0.09] bg-[#0b0b0b]/95 p-8 shadow-[0_32px_100px_rgba(0,0,0,.48)] max-sm:p-6">
      <div className="mb-9 flex items-center gap-3"><LogomarkBadge size={36} /><span className="text-body font-semibold tracking-[.2em]">PENTAGON</span></div>
      <p className="mb-3 text-caption font-medium uppercase tracking-[.22em] text-emerald-200/70">Your models · Your key</p>
      <h1 className="text-display font-medium leading-[1.12] tracking-[-.04em]">Bring your NVIDIA models into focus.</h1>
      <p className="mt-3 text-body leading-6 text-zinc-500">Pentagon checks your key with NVIDIA, then sends it to the backend for encrypted storage. It is never saved in this browser.</p>
      {error && <div role="alert" className="mt-5 rounded-lg border border-rose-400/15 bg-rose-400/[0.06] px-3 py-2 text-small text-rose-200">{error}</div>}
      <form onSubmit={onSubmit} className="mt-7">
        <label htmlFor="nvidia-key" className="mb-2 block text-micro font-medium text-zinc-300">NVIDIA API key</label>
        <input id="nvidia-key" type="password" autoComplete="off" spellCheck={false} value={value} onChange={(event) => onChange(event.target.value)} placeholder="nvapi-••••••••••••••••" className="h-11 w-full rounded-xl border border-white/[0.1] bg-[#000000] px-3.5 text-body text-zinc-100 outline-none placeholder:text-zinc-700 focus:border-emerald-300/40" />
        <div className={`mt-2.5 flex min-h-4 items-center gap-2 text-micro ${tone}`} aria-live="polite"><span className={`size-1.5 rounded-full ${validation === 'valid' ? 'bg-emerald-300' : validation === 'invalid' ? 'bg-rose-300' : validation === 'checking' ? 'animate-pulse bg-amber-200' : 'bg-zinc-700'}`} />{validationMessage}</div>
        <button type="submit" disabled={validation !== 'valid' || saving} className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-300 text-small font-semibold text-[#000000] transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:bg-white/[0.06] disabled:text-zinc-600">{saving ? <LoaderCircle size={14} className="animate-spin" /> : <LockKeyhole size={13} />}{saving ? 'Saving securely…' : 'Store key and continue'}</button>
      </form>
      <div className="mt-7 flex items-center gap-2 border-t border-white/[0.06] pt-5 text-caption leading-5 text-zinc-600"><LockKeyhole size={12} className="shrink-0" />Only the local user ID is kept in browser storage.</div>
    </section>
    <div className="absolute bottom-5 text-caption-xs uppercase tracking-[.2em] text-zinc-700">FastAPI · NVIDIA NIM · Local workspace</div>
  </main>
}

export default App
