import { useCallback, useRef } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import { apiRequest, apiUrl, approvePendingApproval, denyPendingApproval, getCapability, getStoredNvidiaKey, pcmToWavUrl } from '../api'
import type {
  AgentPlanStep,
  ChatMessage,
  CommandRun,
  Conversation,
  ConversationDetail,
  ExecutionTrace,
  PendingToolApproval,
  SourcesUsed,
  TranscriptInfo,
  Verification,
} from './types/app'

/** How often streamed text is committed to the message list. Each commit re-parses
    the answer through react-markdown, so this trades a little latency for a
    steady, inexpensive update rate. */
const STREAM_FLUSH_MS = 45

function decodeAudio(value: string): Uint8Array {
  const raw = atob(value)
  const bytes = new Uint8Array(raw.length)
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index)
  return bytes
}

export interface UseChatStreamOptions {
  userId: string
  agentMode: boolean
  hasActiveThread: boolean
  isDraftThread: boolean
  selectedModel: string
  streaming: boolean
  transcribing: boolean
  uploading: boolean
  // ---- asymmetric: pass through the send/stream side of state ------------
  draft: string
  setDraft: React.Dispatch<React.SetStateAction<string>>
  media: File | null
  setMedia: (file: File | null) => void
  queuedDocuments: File[]
  setQueuedDocuments: React.Dispatch<React.SetStateAction<File[]>>
  transcriptInfo: TranscriptInfo | null
  setTranscriptInfo: (info: TranscriptInfo | null) => void
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  setActive: React.Dispatch<React.SetStateAction<ConversationDetail | Conversation | null>>
  setStreaming: (next: boolean) => void
  setStoppedReply: (next: boolean) => void
  setNotice: (next: string) => void
  setError: (next: string) => void
  setCanRetry: (next: boolean) => void
  setDeciding: (next: string | null) => void
  deciding: string | null
  setRecording: (next: boolean) => void
  setTranscribing: (next: boolean) => void
  recording: boolean
  followConversation: React.MutableRefObject<boolean>
  streamAbort: React.MutableRefObject<AbortController | null>
  createRemoteThread: (firstMessage: string) => Promise<ConversationDetail>
  refreshThreads: () => Promise<Conversation[]>
  refreshBadges: () => Promise<void>
  uploadDocument: (file: File, conversationId: string) => Promise<void>
  acceptFiles: (files: File[]) => Promise<void>
  onAudioUrl: (url: string) => void
  onApprovalResolved?: (conversationId: string) => void
}

/**
 * Everything that turns a composed message into a streamed reply: the send
 * path, the SSE reader, voice recording and transcription, and the agent
 * decision/answer callbacks. Pure behaviour, no JSX — the largest single
 * seam in the original App.tsx.
 */
// eslint-disable-next-line react-hooks/exhaustive-deps
export function useChatStream(options: UseChatStreamOptions) {
  const {
    userId, agentMode, selectedModel, streaming, transcribing, uploading,
    draft, setDraft, media, setMedia, queuedDocuments, setQueuedDocuments,
    transcriptInfo, setTranscriptInfo, setMessages, setActive,
    setStreaming, setStoppedReply, setNotice, setError, setCanRetry,
    setDeciding, deciding, setRecording, setTranscribing, recording,
    followConversation, streamAbort,
  } = options

  const lastSend = useRef<{ question: string; threadId: string; assistantId: string } | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)

  const stopStreaming = useCallback(() => {
    setStoppedReply(true)
    streamAbort.current?.abort()
  }, [setStoppedReply, streamAbort])

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault()
    const typed = draft.trim()
    if (streaming || transcribing || uploading || !options.hasActiveThread || !selectedModel || (!typed && !media)) return
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
    let messageShown = false
    try {
      const thread = await options.createRemoteThread(question)
      lastSend.current = { question, threadId: thread.id, assistantId }
      setCanRetry(false)
      const uploaded: number[] = []
      for (const file of pendingDocs) {
        await options.uploadDocument(file, thread.id)
        uploaded.push(1)
        // Trim as we go, so a failure part-way through leaves exactly the
        // files that never made it, not all of them again.
        setQueuedDocuments((items) => items.slice(uploaded.length))
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
      const savedNvidiaKey = getStoredNvidiaKey()
      if (savedNvidiaKey) form.set('nvidia_key', savedNvidiaKey)
      // Web search is not a user toggle: omitting the field lets the backend
      // router decide when a question actually needs live results.
      if (transcriptInfo && !agentMode) form.set('respond_with_audio', 'true')
      if (mediaForMessage) form.set(isVideo(mediaForMessage) ? 'video' : 'image', mediaForMessage)
      if (transcriptInfo) {
        form.set('transcription_duration_ms', String(transcriptInfo.durationMs))
        form.set('transcription_provider', transcriptInfo.provider)
      }
      setMedia(null)
      await streamResponse(form, assistantId)
      const list = await options.refreshThreads()
      const refreshed = list.find((item) => item.id === thread.id)
      if (refreshed) setActive((current) => current && current.id === refreshed.id ? { ...current, title: refreshed.title, updated_at: refreshed.updated_at } : current)
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        setNotice('Stopped. The partial answer above was kept.')
        if (messageShown) setMessages((current) => current.map((item) => item.id === assistantId && !item.content ? { ...item, content: 'Stopped before an answer was produced.' } : item))
      } else {
        setError(cause instanceof Error ? cause.message : 'The chat request failed.')
        if (messageShown) {
          setCanRetry(true)
          setMessages((current) => current.map((item) => item.id === assistantId && !item.content ? { ...item, content: 'I could not complete that request.' } : item))
        } else {
          // Nothing reached the thread -- creating it or uploading an
          // attachment failed first -- so the question goes back to the
          // composer instead of vanishing along with the cleared draft.
          setDraft((current) => (current.trim() ? current : question))
        }
      }
    } finally {
      setStreaming(false)
      // A finished agent turn is when a new badge may exist: the first turn
      // with a model probes it once and caches the result.
      if (agentMode) void options.refreshBadges()
    }
  }

  async function retryLastMessage() {
    const last = lastSend.current
    if (!last || streaming || !selectedModel) return
    setError('')
    setNotice('')
    setCanRetry(false)
    setStreaming(true)
    setStoppedReply(false)
    setMessages((current) => current.map((item) => (item.id === last.assistantId
      ? {
          ...item,
          content: '',
          turnId: undefined,
          agentSteps: undefined,
          agentPlan: undefined,
          agentArtifacts: undefined,
          agentQuestion: null,
          pendingToolApproval: null,
          verification: undefined,
          statusNotes: undefined,
        }
      : item)))
    const form = new FormData()
    form.set('user_id', userId)
    form.set('conversation_id', last.threadId)
    form.set('model', selectedModel)
    form.set('message', last.question)
    // Regenerate: the question is already the thread's last row.
    form.set('regenerate', 'true')
    try {
      await streamResponse(form, last.assistantId)
      const list = await options.refreshThreads()
      const refreshed = list.find((item) => item.id === last.threadId)
      if (refreshed) setActive((current) => current && current.id === refreshed.id ? { ...current, title: refreshed.title, updated_at: refreshed.updated_at } : current)
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        setNotice('Stopped. The partial answer above was kept.')
      } else {
        setError(cause instanceof Error ? cause.message : 'The chat request failed.')
        setCanRetry(true)
      }
    } finally {
      setStreaming(false)
      if (agentMode) void options.refreshBadges()
    }
  }

  /** Answer an approval card (agent or chat graph). */
  async function decideAgentTools(turnId: string, callIds: string[]) {
    if (deciding) return
    setDeciding(turnId)
    try {
      if (agentMode) {
        await apiRequest('/api/agent/decisions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, turn_id: turnId, call_ids: callIds }),
        })
      } else {
        await approvePendingApproval(turnId, userId)
        if (options.onApprovalResolved) {
          options.onApprovalResolved(turnId)
        }
      }
      setMessages((current) => current.map((item) => (item.turnId === turnId && item.pendingToolApproval ? { ...item, pendingToolApproval: null } : item)))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not send your approval.')
    } finally {
      setDeciding(null)
    }
  }

  /** Decline: an empty list means nothing on the card may run. */
  async function denyAgentTools(turnId: string) {
    if (deciding) return
    setDeciding(turnId)
    try {
      if (agentMode) {
        await apiRequest('/api/agent/decisions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, turn_id: turnId, call_ids: [] }),
        })
      } else {
        await denyPendingApproval(turnId, userId)
        if (options.onApprovalResolved) {
          options.onApprovalResolved(turnId)
        }
      }
      setMessages((current) => current.map((item) => (item.turnId === turnId && item.pendingToolApproval ? { ...item, pendingToolApproval: null } : item)))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not send your decision.')
    } finally {
      setDeciding(null)
    }
  }

  /** Answer a question the turn asked through ask_user. */
  async function answerAgentQuestion(turnId: string, text: string) {
    if (deciding) return
    setDeciding(turnId)
    try {
      await apiRequest('/api/agent/answers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, turn_id: turnId, answer: text }),
      })
      setMessages((current) => current.map((item) => (item.turnId === turnId && item.agentQuestion ? { ...item, agentQuestion: { ...item.agentQuestion, answered: true } } : item)))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not send your answer.')
    } finally {
      setDeciding(null)
    }
  }

  /** Answer the approval prompt. The turn stays blocked until the server hears this. */
  async function decideCommand(requestId: string, approved: boolean, value?: Record<string, unknown>) {
    if (deciding) return
    setDeciding(requestId)
    try {
      await apiRequest('/api/commands/decide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: requestId, approved, user_id: userId, value: value ?? {} }),
      })
      // Clear the prompt whether or not the write landed: if the request failed
      // the server is no longer waiting, and a card the user cannot dismiss is
      // worse than one that disappears.
      setMessages((current) =>
        current.map((item) =>
          item.pendingCommand?.request_id === requestId
            ? { ...item, pendingCommand: null }
            : item,
        ),
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not send your decision.')
    } finally {
      setDeciding(null)
    }
  }

  async function streamResponse(form: FormData, assistantId: string) {
    const controller = new AbortController()
    streamAbort.current = controller
    const capability = await getCapability()
    const headers: Record<string, string> = { Accept: 'text/event-stream' }
    if (capability) headers['X-Pentagon-Capability'] = capability
    const savedNvidiaKey = getStoredNvidiaKey()
    if (savedNvidiaKey) headers['X-Nvidia-Key'] = savedNvidiaKey
    const hasMedia = form.has('image') || form.has('video')
    const endpoint = hasMedia ? '/api/chat' : (agentMode ? '/api/agent/chat' : '/api/chat')
    const response = await fetch(apiUrl(endpoint), {
      method: 'POST',
      body: form,
      headers,
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
    // A stream that sends nothing at all is dead, not slow. The server emits a
    // keep-alive comment every second while it waits (on the model, or on an
    // approval card), so any real silence this long means the connection or
    // the backend is gone and the UI must say so instead of spinning forever.
    // Bytes of any kind -- tokens, events, pings -- re-arm the timer.
    const SSE_READ_STALL_MS = 75_000
    let stallTimer: number | null = null
    let stallError: Error | null = null
    const armStallTimer = () => {
      if (stallTimer !== null) window.clearTimeout(stallTimer)
      stallTimer = window.setTimeout(() => {
        stallTimer = null
        // Recorded, not thrown, from here: a timer callback cannot reject into
        // the reader loop. The loop re-throws it once the abort lands.
        stallError = new Error('The connection to Pentagon stopped responding. Please try again.')
        streamAbort.current?.abort()
      }, SSE_READ_STALL_MS)
    }
    armStallTimer()
    const update = (changes: Partial<ChatMessage>) => setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, ...changes } : item))
    /** Functional variant: appending to an agent timeline needs the previous item, not a patch. */
    const mutate = (fn: (item: ChatMessage) => ChatMessage) => setMessages((current) => current.map((item) => (item.id === assistantId ? fn(item) : item)))
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
      const dynamicWait = bufferedText.length > 3000 ? 90 : STREAM_FLUSH_MS
      const wait = Math.max(0, dynamicWait - (performance.now() - lastFlushAt))
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
          // Only set when the turn actually ran commands, so a normal reply
          // leaves the previous value alone rather than clearing it.
          ...(Array.isArray(payload.command_runs)
            ? { commandRuns: payload.command_runs as CommandRun[] }
            : {}),
        })
      } else if (eventName === 'audio_chunk' && typeof payload.content === 'string') {
        audioChunks.push(decodeAudio(payload.content))
        if (typeof payload.sample_rate_hz === 'number') sampleRate = payload.sample_rate_hz
        if (typeof payload.channels === 'number') channels = payload.channels
      } else if (eventName === 'audio_end') {
        if (typeof payload.sample_rate_hz === 'number') sampleRate = payload.sample_rate_hz
        if (typeof payload.channels === 'number') channels = payload.channels
        const audioUrl = pcmToWavUrl(audioChunks, sampleRate, channels)
        if (audioUrl) {
          options.onAudioUrl(audioUrl)
          update({ audioUrl })
        }
        audioChunks = []
      } else if (eventName === 'audio_error') {
        setError(String(payload.message || 'The text response is ready, but speech synthesis failed.'))
      } else if (eventName === 'conversation' && typeof payload.turn_id === 'string') {
        // Graph replies carry no turn id; agent turns carry the one the
        // decision routes need.
        mutate((item) => ({ ...item, turnId: payload.turn_id as string }))
      } else if (eventName === 'tool_start') {
        mutate((item) => ({
          ...item,
          agentSteps: [...(item.agentSteps ?? []), { id: String(payload.id ?? crypto.randomUUID()), tool: String(payload.tool ?? 'tool'), status: 'running' }],
        }))
      } else if (eventName === 'tool_result') {
        mutate((item) => ({
          ...item,
          agentSteps: (item.agentSteps ?? []).map((step) => step.id === String(payload.id)
            ? {
                ...step,
                status: payload.ok ? 'ok' : 'error',
                summary: typeof payload.summary === 'string' ? payload.summary : step.summary,
                elapsed_ms: typeof payload.elapsed_ms === 'number' ? payload.elapsed_ms : step.elapsed_ms,
              }
            : step),
        }))
      } else if (eventName === 'status') {
        const note = typeof payload.message === 'string' ? payload.message : ''
        const revised = typeof payload.answer === 'string' ? payload.answer : null
        // A repaired answer supersedes the tokens that already streamed.
        if (revised !== null) bufferedText = ''
        mutate((item) => ({
          ...item,
          ...(note ? { statusNotes: [...(item.statusNotes ?? []), note] } : {}),
          ...(revised !== null ? { content: revised } : {}),
        }))
      } else if (eventName === 'plan') {
        mutate((item) => ({ ...item, agentPlan: Array.isArray(payload.steps) ? payload.steps as AgentPlanStep[] : item.agentPlan }))
      } else if (eventName === 'ask_user') {
        mutate((item) => ({
          ...item,
          agentQuestion: {
            question: String(payload.question ?? ''),
            options: Array.isArray(payload.options) ? payload.options.map(String) : [],
            answered: false,
          },
        }))
      } else if (eventName === 'artifact') {
        mutate((item) => {
          const id = String(payload.id ?? payload.name ?? 'artifact')
          if ((item.agentArtifacts ?? []).some((entry) => entry.id === id)) return item
          return {
            ...item,
            agentArtifacts: [...(item.agentArtifacts ?? []), {
              id,
              name: String(payload.name ?? id),
              path: typeof payload.path === 'string' ? payload.path : undefined,
              bytes: typeof payload.bytes === 'number' ? payload.bytes : undefined,
            }],
          }
        })
      } else if (eventName === 'generated_file' || eventName === 'file') {
        const record = payload as unknown as GeneratedFileInfo
        if (record && record.id) {
          mutate((item) => {
            const existing = item.generatedFiles ?? []
            if (existing.some((f) => f.id === record.id)) return item
            return {
              ...item,
              generatedFiles: [...existing, record],
            }
          })
        }
      } else if (eventName === 'approval_required') {
        const interrupt = payload.interrupt as Record<string, unknown> | undefined
        const calls = Array.isArray(payload.calls)
          ? (payload.calls as PendingToolApproval['calls'])
          : interrupt
            ? [
                {
                  id: String(interrupt.tool_call_id || crypto.randomUUID()),
                  tool: String(interrupt.tool_name || 'tool'),
                  tier: String(interrupt.category || 'write'),
                },
              ]
            : []
        const effectiveTurnId = String(payload.turn_id ?? payload.conversation_id ?? '')
        mutate((item) => ({
          ...item,
          turnId: effectiveTurnId || item.turnId,
          pendingToolApproval: {
            turn_id: effectiveTurnId || item.turnId || '',
            calls,
          },
        }))
      } else if (eventName === 'done') {
        mutate((item) => ({
          ...item,
          ...(payload.verification ? { verification: payload.verification as Verification } : {}),
          // Whatever was still waiting is closed by the turn's end.
          pendingToolApproval: null,
          agentQuestion: null,
        }))
      } else if (eventName === 'error') {
        const raw = String(payload.message || 'The model request failed.')
        if (raw.includes('Not found for account') || raw.includes('Function \'')) {
          throw new Error('NVIDIA Cloud Error: The requested model is not available or not provisioned for your NVIDIA account. Please switch to an active model (such as Llama 3.1 Nemotron or Llama 3.2 Vision) using the model selector.')
        }
        throw new Error(raw)
      }
    }
    try {
      while (true) {
        const { value, done } = await reader.read()
        if (stallError) throw stallError
        if (done) break
        armStallTimer()
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
      if (stallError) throw stallError
    } catch (cause) {
      // A stall aborts its own stream, so the read rejects with a plain
      // AbortError; re-throw the recorded reason instead of letting that look
      // like the user pressing Stop.
      if (stallError) throw stallError
      throw cause
    } finally {
      if (stallTimer !== null) window.clearTimeout(stallTimer)
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
    await options.acceptFiles(files)
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

  return {
    sendMessage,
    stopStreaming,
    toggleRecording,
    transcribeRecording,
    handleAttachmentChange,
    handleSubmit,
    handleComposerKey,
    decideAgentTools,
    denyAgentTools,
    answerAgentQuestion,
    decideCommand,
    retryLastMessage,
  }
}

export interface GeneratedFileInfo {
  id: string
  filename: string
  format: string
  media_type: string
  size: number
  conversation_id: string
  created_at: string | null
  storage_path: string
}

function isVideo(file: File): boolean {
  return file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi)$/i.test(file.name)
}
