export type ModelInfo = { id: string; supports_vision?: boolean }

export type Conversation = {
  id: string
  title: string
  updated_at: string
  active_model: string | null
  summary_at_switch?: string | null
  isDraft?: boolean
}

export type TraceEntry = Record<string, unknown> & {
  status?: string
  duration_ms?: number
}

export type ExecutionTrace = Record<string, TraceEntry>

export type SourcesUsed = {
  web?: Array<{ title: string; url: string }>
  documents?: Array<{ document_id: string; filename: string; chunk_ids: string[] }>
  image?: { model_used: string; description_summary: string }
  video?: { model_used: string; description_summary: string; frames_sent: number; sampling_fps?: number }
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  model_used: string
  created_at?: string
  // No image_path: the API used to send the absolute server path the upload
  // was written to. Nothing here ever read it.
  attachmentName?: string
  execution_trace?: ExecutionTrace
  sources_used?: SourcesUsed
  audioUrl?: string
  /** Awaiting the user's decision. Present only while the prompt is showing. */
  pendingCommand?: PendingCommand | null
  /** What the commands actually did, once the turn finished. */
  commandRuns?: CommandRun[]
}

export type DocumentInfo = {
  document_id: string
  filename: string
  chunks_stored: number
  created_at?: string
}

/** What the backend recorded about one command it ran, or refused to run. */
export type CommandRun = {
  command: string
  exit_code: number | null
  stdout: string
  stderr: string
  duration_ms: number
  timed_out: boolean
  /** False when the user declined: nothing ran and exit_code is null. */
  auto_approved: boolean
  truncated: boolean
  ok: boolean
}

/** A command the model wants that needs the user's yes before it runs. */
export type PendingCommand = {
  request_id: string
  command: string
  reason: string
}

export type CommandSettings = {
  /** The user opted in, and the server permits it. */
  enabled: boolean
  /** Whether the server exposes the tool at all. */
  available: boolean
  approval_timeout_seconds: number
}
