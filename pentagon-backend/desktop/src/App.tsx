import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'

type ValidationState = 'idle' | 'checking' | 'valid' | 'invalid'
type ModelInfo = { id: string; supports_vision: boolean }
type Conversation = { id: string; title: string; active_model: string | null; updated_at: string }
type DocumentInfo = { document_id: string; filename: string; chunks_stored: number }
type Sources = {
  web?: Array<{ title: string; url: string }>
  documents?: Array<{ document_id: string; filename: string; chunk_ids: string[] }>
  image?: { model_used: string; description_summary: string }
  video?: { model_used: string; description_summary: string; frames_sent: number }
}
type Trace = Record<string, { status?: string; duration_ms?: number; model_used?: string }>
type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  model_used: string
  created_at?: string
  image_path?: string | null
  attachment?: string
  sources?: Sources
  trace?: Trace
}
type ConversationDetail = Conversation & { summary_at_switch: string | null; messages: ChatMessage[] }
type TranscriptInfo = { duration: number; provider: string }

class ApiError extends Error {
  status: number

  constructor(message: string, status: number) { super(message); this.status = status }
}

function getUserId(): string {
  const storageKey = 'pentagon.userId'
  const existing = localStorage.getItem(storageKey)
  if (existing) return existing
  const id = `pentagon-${crypto.randomUUID()}`
  localStorage.setItem(storageKey, id)
  return id
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: string | Array<{ msg?: string }> }
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((item) => item.msg).filter(Boolean).join(', ') || message
    } catch { /* Use the HTTP status when the response is not JSON. */ }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

function safeUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : null
  } catch { return null }
}

function pcmBytes(value: string): Uint8Array {
  const decoded = atob(value)
  const output = new Uint8Array(decoded.length)
  for (let i = 0; i < decoded.length; i += 1) output[i] = decoded.charCodeAt(i)
  return output
}

async function playPcm(chunks: Uint8Array[], sampleRate: number, channels: number) {
  const length = chunks.reduce((total, item) => total + item.length, 0)
  if (!length || !window.AudioContext) return
  const pcm = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { pcm.set(chunk, offset); offset += chunk.length }
  const frames = Math.floor(pcm.length / 2 / Math.max(channels, 1))
  if (!frames) return
  const context = new AudioContext()
  const buffer = context.createBuffer(channels, frames, sampleRate)
  const view = new DataView(pcm.buffer)
  for (let channel = 0; channel < channels; channel += 1) {
    const samples = buffer.getChannelData(channel)
    for (let frame = 0; frame < frames; frame += 1) {
      samples[frame] = view.getInt16((frame * channels + channel) * 2, true) / 32768
    }
  }
  const source = context.createBufferSource()
  source.buffer = buffer
  source.connect(context.destination)
  source.onended = () => void context.close()
  source.start()
}

function App() {
  const [userId] = useState(getUserId)
  const [ready, setReady] = useState(false)
  const [needsKey, setNeedsKey] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [keyError, setKeyError] = useState('')
  const [validation, setValidation] = useState<ValidationState>('idle')
  const [validationText, setValidationText] = useState('')
  const [savingKey, setSavingKey] = useState(false)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [active, setActive] = useState<ConversationDetail | null>(null)
  const [model, setModel] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [draft, setDraft] = useState('')
  const [image, setImage] = useState<File | null>(null)
  const [video, setVideo] = useState<File | null>(null)
  const [webSearch, setWebSearch] = useState(false)
  const [audioReply, setAudioReply] = useState(false)
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const documentInput = useRef<HTMLInputElement>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const loadDocuments = useCallback(async (conversationId: string) => {
    try {
      const result = await jsonRequest<DocumentInfo[]>(`/api/documents?user_id=${encodeURIComponent(userId)}&conversation_id=${encodeURIComponent(conversationId)}`)
      setDocuments(result)
    } catch { setDocuments([]) }
  }, [userId])

  const loadConversation = useCallback(async (id: string, modelList = models) => {
    setLoading(true)
    setError('')
    try {
      const data = await jsonRequest<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`)
      setActive(data)
      setModel(data.active_model || modelList[0]?.id || '')
      setMessages(data.messages.map((item) => ({
        ...item,
        attachment: item.image_path ? 'Image attached' : undefined,
      })))
      await loadDocuments(id)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load the conversation.') }
    finally { setLoading(false) }
  }, [loadDocuments, models])

  const bootstrap = useCallback(async () => {
    setReady(false)
    setKeyError('')
    try {
      const result = await jsonRequest<{ models: ModelInfo[] }>(`/api/models?user_id=${encodeURIComponent(userId)}`)
      setModels(result.models)
      setNeedsKey(false)
      const list = await jsonRequest<Conversation[]>(`/api/conversations?user_id=${encodeURIComponent(userId)}`)
      setConversations(list)
      if (list.length) await loadConversation(list[0].id, result.models)
      else { setActive(null); setMessages([]); setDocuments([]); setModel(result.models[0]?.id || '') }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) setNeedsKey(true)
      else setKeyError(cause instanceof Error ? cause.message : 'Could not reach the backend.')
    } finally { setReady(true) }
  }, [loadConversation, userId])

  // Startup hydration intentionally writes the remote conversation state into React.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { void bootstrap() }, [bootstrap])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages])
  useEffect(() => () => recorder.current?.stream.getTracks().forEach((track) => track.stop()), [])

  useEffect(() => {
    if (!keyInput.trim()) return
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        const data = await jsonRequest<{ valid: boolean; reason?: string }>('/api/keys/validate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: keyInput }),
        })
        if (cancelled) return
        setValidation(data.valid ? 'valid' : 'invalid')
        setValidationText(data.valid ? 'Key verified with NVIDIA.' : data.reason || 'NVIDIA rejected this key.')
      } catch (cause) {
        if (!cancelled) {
          setValidation('invalid')
          setValidationText(cause instanceof Error ? cause.message : 'Could not validate this key.')
        }
      }
    }, 600)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [keyInput])

  async function refreshConversations() {
    const list = await jsonRequest<Conversation[]>(`/api/conversations?user_id=${encodeURIComponent(userId)}`)
    setConversations(list)
    return list
  }

  async function storeKey(event: FormEvent) {
    event.preventDefault()
    if (validation !== 'valid' || savingKey) return
    setSavingKey(true)
    try {
      await jsonRequest('/api/keys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, api_key: keyInput }),
      })
      setKeyInput('')
      setValidation('idle')
      setNeedsKey(false)
      await bootstrap()
    } catch (cause) { setKeyError(cause instanceof Error ? cause.message : 'Could not store the key.') }
    finally { setSavingKey(false) }
  }

  async function newConversation() {
    setError('')
    try {
      const data = await jsonRequest<Conversation>('/api/conversations', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      })
      const fresh = { ...data, active_model: null }
      setConversations((current) => [fresh, ...current])
      setActive({ ...fresh, summary_at_switch: null, messages: [] })
      setMessages([]); setDocuments([]); setModel(models[0]?.id || '')
      setNotice('New conversation ready.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not create a conversation.') }
  }

  async function switchModel(nextModel: string) {
    if (!active || nextModel === model || switching) return
    setSwitching(true); setError(''); setNotice('')
    try {
      const result = await jsonRequest<{ active_model: string; summary_generated: boolean; summary_word_count: number }>(
        `/api/conversations/${encodeURIComponent(active.id)}`,
        { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: nextModel }) },
      )
      setModel(result.active_model)
      setConversations((current) => current.map((item) => item.id === active.id ? { ...item, active_model: result.active_model } : item))
      setNotice(result.summary_generated
        ? `Context summarized for the new model (${result.summary_word_count} words); six recent messages are retained.`
        : 'Conversation model updated.')
      await loadConversation(active.id, models)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not switch models.') }
    finally { setSwitching(false) }
  }

  async function sendMessage(text: string, imageFile: File | null = image, videoFile: File | null = video, transcript?: TranscriptInfo) {
    if (!active || !model || sending || (!text.trim() && !imageFile && !videoFile)) return
    const question = text.trim() || (videoFile ? 'Describe what happens in this video with timestamps.' : 'Describe what is in this image.')
    const attachment = [imageFile?.name, videoFile?.name].filter(Boolean).join(', ')
    const userMessageId = crypto.randomUUID()
    const assistantMessageId = crypto.randomUUID()
    setError(''); setNotice(''); setDraft(''); setImage(null); setVideo(null); setSending(true)
    setMessages((current) => [
      ...current,
      { id: userMessageId, role: 'user', content: question, model_used: model, attachment: attachment || undefined },
      { id: assistantMessageId, role: 'assistant', content: '', model_used: model },
    ])
    const form = new FormData()
    form.set('user_id', userId); form.set('conversation_id', active.id); form.set('model', model)
    form.set('message', question); form.set('use_web_search', String(webSearch)); form.set('respond_with_audio', String(audioReply))
    if (imageFile) form.set('image', imageFile)
    if (videoFile) form.set('video', videoFile)
    if (transcript) {
      form.set('transcription_duration_ms', String(transcript.duration))
      form.set('transcription_provider', transcript.provider)
    }
    try {
      await consumeChat(form, (event, payload) => {
        const token = payload.content
        if (event === 'token' && typeof token === 'string') {
          setMessages((current) => current.map((item) => item.id === assistantMessageId ? { ...item, content: item.content + token } : item))
        } else if (event === 'metadata') {
          setMessages((current) => current.map((item) => item.id === assistantMessageId
            ? { ...item, sources: payload.sources_used as Sources, trace: payload.execution_trace as Trace }
            : item))
        } else if (event === 'audio_error') setError(String(payload.message || 'Audio synthesis failed.'))
      })
      const list = await refreshConversations()
      const updated = list.find((item) => item.id === active.id)
      if (updated) setActive((current) => current ? { ...current, title: updated.title } : current)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'The chat request failed.'
      setMessages((current) => current.map((item) => item.id === assistantMessageId
        ? { ...item, content: item.content || `I couldn't complete that request. ${message}` }
        : item))
      setError(message)
    } finally { setSending(false) }
  }

  async function consumeChat(form: FormData, onEvent: (event: string, payload: Record<string, unknown>) => void) {
    const response = await fetch('/api/chat', { method: 'POST', body: form })
    if (!response.ok) {
      let message = `Chat request failed (${response.status})`
      try { message = (await response.json() as { detail?: string }).detail || message } catch { /* Use status text. */ }
      throw new ApiError(message, response.status)
    }
    if (!response.body) throw new Error('The backend did not open a response stream.')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let pending = ''
    const audioChunks: Uint8Array[] = []
    let sampleRate = 22050
    let channels = 1
    const dispatch = (block: string) => {
      const lines = block.split('\n')
      const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
      const rawData = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
      if (!rawData) return
      let payload: Record<string, unknown>
      try { payload = JSON.parse(rawData) as Record<string, unknown> } catch { return }
      if (event === 'error') throw new Error(String(payload.message || 'The chat request failed.'))
      if (event === 'audio_chunk' && typeof payload.content === 'string') {
        audioChunks.push(pcmBytes(payload.content))
        if (typeof payload.sample_rate_hz === 'number') sampleRate = payload.sample_rate_hz
        if (typeof payload.channels === 'number') channels = payload.channels
      }
      if (event === 'audio_end') {
        if (typeof payload.sample_rate_hz === 'number') sampleRate = payload.sample_rate_hz
        if (typeof payload.channels === 'number') channels = payload.channels
        void playPcm(audioChunks, sampleRate, channels).catch(() => setError('Audio could not be played on this device.'))
      }
      onEvent(event, payload)
    }
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
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
  }

  function submit(event: FormEvent) { event.preventDefault(); void sendMessage(draft) }
  function composerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendMessage(draft) }
  }
  function selectAttachment(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi)$/i.test(file.name)) { setVideo(file); setImage(null) }
    else { setImage(file); setVideo(null) }
  }

  async function uploadDocument(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !active) return
    const form = new FormData()
    form.set('user_id', userId); form.set('conversation_id', active.id); form.set('file', file)
    setUploading(true); setError('')
    try {
      const result = await jsonRequest<{ filename: string; chunks_stored: number }>('/api/documents/upload', { method: 'POST', body: form })
      await loadDocuments(active.id)
      setNotice(`${result.filename} added (${result.chunks_stored} passages).`)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Document upload failed.') }
    finally { setUploading(false) }
  }

  async function toggleMic() {
    if (recording) { recorder.current?.stop(); setRecording(false); return }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') { setError('Audio recording is unavailable in this environment.'); return }
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const chunks: Blob[] = []
      const media = new MediaRecorder(stream)
      recorder.current = media
      media.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      media.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
        recorder.current = null
        const mime = media.mimeType || 'audio/webm'
        const ext = mime.includes('wav') ? 'wav' : mime.includes('mpeg') ? 'mp3' : 'webm'
        void transcribeAndSend(new Blob(chunks, { type: mime }), ext)
      }
      media.start(); setRecording(true)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Microphone permission was denied.') }
  }

  async function transcribeAndSend(blob: Blob, extension: string) {
    setTranscribing(true); setError('')
    const form = new FormData()
    form.set('user_id', userId); form.set('file', blob, `recording.${extension}`)
    try {
      const result = await jsonRequest<{ text: string; execution_trace?: { transcription?: { duration_ms?: number; provider?: string } } }>(
        '/api/voice/transcribe', { method: 'POST', body: form },
      )
      if (!result.text.trim()) { setNotice('No speech was detected. Try a clearer recording.'); return }
      const trace = result.execution_trace?.transcription
      await sendMessage(result.text, null, null, { duration: trace?.duration_ms || 0, provider: trace?.provider || 'unspecified' })
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not transcribe this recording.') }
    finally { setTranscribing(false) }
  }

  const currentModel = models.find((item) => item.id === model)
  const attachment = image || video

  if (!ready) return <div className="boot-screen"><span className="brand-mark">P</span><p>Connecting to Pentagon…</p></div>
  if (needsKey || keyError) return (
    <main className="key-screen">
      <div className="key-glow" />
      <section className="key-card">
        <div className="brand-lockup"><span className="brand-mark">P</span><span>PENTAGON</span></div>
        <p className="eyebrow">YOUR MODELS. YOUR KEY.</p>
        <h1>Bring your NVIDIA models into one clear workspace.</h1>
        <p className="key-description">The key stays on the backend. Pentagon validates it live, then stores it encrypted for this local user.</p>
        {keyError && <div className="alert error-alert">{keyError}<button onClick={() => void bootstrap()}>Retry</button></div>}
        <form className="key-form" onSubmit={(event) => void storeKey(event)}>
          <label htmlFor="api-key">NVIDIA API key</label>
          <input id="api-key" type="password" value={keyInput} onChange={(event) => {
            const value = event.target.value
            setKeyInput(value)
            setValidation(value.trim() ? 'checking' : 'idle')
            setValidationText('')
          }} placeholder="nvapi-…" autoComplete="off" spellCheck={false} />
          <div className={`validation-line validation-${validation}`} aria-live="polite"><span className="validation-dot" />{validationText || 'Validation runs as you type.'}</div>
          <button className="primary-button key-submit" disabled={validation !== 'valid' || savingKey}>{savingKey ? 'Saving securely…' : 'Store key and continue'}<span>↗</span></button>
        </form>
        <div className="key-footnote">▣ <span>Only your user ID is saved here. The key is never written to browser storage.</span></div>
        <div className="user-id">LOCAL USER · {userId.slice(0, 20)}</div>
      </section>
      <div className="key-side-note">FASTAPI · LANGGRAPH · NVIDIA NIM</div>
    </main>
  )

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup sidebar-brand"><span className="brand-mark">P</span><span>PENTAGON</span></div>
        <div className="sidebar-heading"><span>WORKSPACE</span><span className="live-label"><i /> LIVE</span></div>
        <button className="new-chat-button" onClick={() => void newConversation()}><span>＋</span> New conversation</button>
        <div className="sidebar-heading conversation-heading"><span>CONVERSATIONS</span><span>{conversations.length.toString().padStart(2, '0')}</span></div>
        <nav className="conversation-list" aria-label="Conversations">
          {conversations.map((item) => <button key={item.id} className={`conversation-row ${active?.id === item.id ? 'conversation-active' : ''}`} onClick={() => void loadConversation(item.id)}>
            <span className="conversation-icon">◌</span><span className="conversation-copy"><strong>{item.title || 'New conversation'}</strong><small>{new Date(item.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</small></span>
          </button>)}
          {!conversations.length && <p className="sidebar-empty">Your conversations will appear here.</p>}
        </nav>
        <div className="sidebar-bottom">
          <div className="user-badge"><span className="user-avatar">{userId.slice(-1).toUpperCase()}</span><span><strong>Local workspace</strong><small>Key encrypted on backend</small></span><i /></div>
          <button className="subtle-button" onClick={() => { setNeedsKey(true); setKeyInput(''); setValidation('idle'); setValidationText(''); setKeyError('') }}>Change NVIDIA key</button>
        </div>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div className="breadcrumb"><span className="mobile-brand">P</span> Pentagon <b>/</b> {active?.title || 'New conversation'}</div>
          <div className="model-controls"><span className="model-label">MODEL</span>
            <select value={model} onChange={(event) => void switchModel(event.target.value)} disabled={!active || switching || sending} aria-label="Conversation model">
              {!models.length && <option value="">No models available</option>}
              {models.map((item) => <option value={item.id} key={item.id}>{item.id}{item.supports_vision ? ' · Vision' : ''}</option>)}
            </select>
            <span className={`capability ${currentModel?.supports_vision ? 'vision-capability' : ''}`}>{currentModel?.supports_vision ? '◈ Vision' : 'Text'}</span>
          </div>
        </header>

        <div className="chat-stage">
          <div className="chat-scroll">
            {loading ? <div className="empty-state"><span className="loader-ring" /><p>Loading conversation…</p></div>
              : messages.length ? <div className="message-list">{messages.map((item) => <MessageView message={item} key={item.id} />)}<div ref={bottom} /></div>
                : <div className="welcome-state">
                  <div className="welcome-symbol">✳<i /><i /><i /></div><p className="eyebrow">A MULTIMODAL WORKSPACE</p>
                  <h1>What are we<br /><em>working on?</em></h1>
                  <p className="welcome-copy">Ask a question, bring a file into context, or speak your next idea.</p>
                  <div className="suggestion-grid">
                    <button onClick={() => setDraft('Explain the key ideas in my uploaded documents.')}>⌕ <span>Search my documents</span><b>↗</b></button>
                    <button onClick={() => setDraft('What are the important details in this image?')}>◈ <span>Understand an image</span><b>↗</b></button>
                    <button onClick={() => setDraft('Summarize the distinct moments in this video with timestamps.')}>▣ <span>Review a video clip</span><b>↗</b></button>
                    <button onClick={() => { setWebSearch(true); setDraft('Give me a concise answer with current sources.') }}>↗ <span>Research a current topic</span><b>↗</b></button>
                  </div>
                </div>}
          </div>

          <div className="composer-wrap">
            {notice && <div className="notice-line" role="status">{notice}<button onClick={() => setNotice('')} aria-label="Dismiss">×</button></div>}
            {error && <div className="alert inline-error" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss">×</button></div>}
            {attachment && <div className="attachment-chip"><span>{video ? '▣' : '◈'}</span>{attachment.name}<button onClick={() => { setImage(null); setVideo(null) }} aria-label="Remove attachment">×</button></div>}
            <form className="composer" onSubmit={(event) => void submit(event)}>
              <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={composerKey} rows={2} placeholder="Message Pentagon…" disabled={!active || sending || transcribing} aria-label="Message" />
              <div className="composer-toolbar">
                <div className="composer-tools">
                  <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo" hidden onChange={selectAttachment} />
                  <button type="button" className="tool-button" onClick={() => fileInput.current?.click()} disabled={sending} title="Attach an image or video"><span>＋</span><label>Attach</label></button>
                  <button type="button" className={`tool-button ${recording ? 'recording' : ''}`} onClick={() => void toggleMic()} disabled={sending || transcribing} title={recording ? 'Stop and transcribe' : 'Record a voice message'}><span>{recording ? '■' : '◉'}</span><label>{recording ? 'Stop' : 'Voice'}</label></button>
                  <button type="button" className={`tool-button ${audioReply ? 'tool-selected' : ''}`} onClick={() => setAudioReply((value) => !value)} aria-pressed={audioReply} title="Read the response aloud"><span>♫</span><label>Voice reply</label></button>
                  <button type="button" className={`tool-button ${webSearch ? 'tool-selected' : ''}`} onClick={() => setWebSearch((value) => !value)} aria-pressed={webSearch} title="Include web search"><span>⌕</span><label>Web search</label></button>
                  <input ref={documentInput} type="file" accept=".pdf,.docx,.txt" hidden onChange={(event) => void uploadDocument(event)} />
                  <button type="button" className="tool-button" onClick={() => documentInput.current?.click()} disabled={!active || uploading} title="Upload a document"><span>▤</span><label>{uploading ? 'Uploading…' : 'Document'}</label></button>
                </div>
                <button className="send-button" type="submit" disabled={sending || transcribing || (!draft.trim() && !image && !video)} aria-label="Send message">{sending || transcribing ? <span className="send-spinner" /> : '↑'}</button>
              </div>
            </form>
            <div className="composer-footer"><span>{transcribing ? 'Transcribing voice…' : sending ? 'Generating response…' : 'Enter to send · Shift + Enter for a new line'}</span><span>{model || 'Choose a model'}{currentModel?.supports_vision ? ' · Vision ready' : ''}</span></div>
          </div>
        </div>

        <aside id="active-documents" className="documents-strip">
          <div className="documents-label"><span>▤</span><div><strong>{documents.length} active {documents.length === 1 ? 'document' : 'documents'}</strong><small>Conversation knowledge</small></div></div>
          <div className="document-list">{documents.map((item) => <span className="document-pill" key={item.document_id} title={`${item.chunks_stored} passages`}>{item.filename}<small>{item.chunks_stored}</small></span>)}{!documents.length && <span className="no-documents">Add a PDF, DOCX, or TXT file to search this conversation.</span>}</div>
        </aside>
      </section>
    </main>
  )
}

function MessageView({ message }: { message: ChatMessage }) {
  const assistant = message.role === 'assistant'
  const sources = message.sources
  const vision = message.trace?.vision_analysis
  return <article className={`message-row ${assistant ? 'assistant-row' : 'user-row'}`}>
    {assistant && <div className="message-avatar assistant-avatar">P</div>}
    <div className="message-content">
      <div className="message-heading"><strong>{assistant ? 'Pentagon' : 'You'}</strong>{assistant && <span>{message.model_used}</span>}</div>
      <div className={`message-bubble ${assistant ? 'assistant-bubble' : 'user-bubble'}`}>
        {message.content ? <p>{message.content}</p> : <span className="typing-dots"><i /><i /><i /></span>}
        {message.attachment && <div className="message-attachment">◈ {message.attachment}</div>}
      </div>
      {assistant && <div className="citations">
        {(sources?.web || []).map((source, index) => {
          const href = safeUrl(source.url)
          return href ? <a key={`${href}-${index}`} href={href} target="_blank" rel="noreferrer" className="citation-link">↗ {source.title || new URL(href).hostname}</a> : null
        })}
        {(sources?.documents || []).map((source) => <a key={source.document_id} href="#active-documents" className="citation-link">▤ {source.filename} · {source.chunk_ids.length} passages</a>)}
        {sources?.image && <span className="citation-link">◈ Image · {sources.image.model_used}</span>}
        {sources?.video && <span className="citation-link">▣ Video · {sources.video.frames_sent} frames</span>}
      </div>}
      {assistant && vision?.status && <div className="trace-note">{vision.status === 'ran' ? 'Vision analysis' : 'Vision analysis unavailable'}{vision.duration_ms ? ` · ${(vision.duration_ms / 1000).toFixed(1)}s` : ''}</div>}
    </div>
    {!assistant && <div className="message-avatar user-message-avatar">Y</div>}
  </article>
}

export default App
