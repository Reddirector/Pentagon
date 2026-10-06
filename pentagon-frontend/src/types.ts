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

export type MemoryInfo = {
  id: string
  label: string
  text: string
  created_at: string
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
  /** What will actually happen, resolved before asking. Empty for shell commands. */
  detail?: string
  /** "command" is answered yes/no; "location" is answered with coordinates. */
  kind?: 'command' | 'location'
}

export type CommandSettings = {
  /** The user opted in, and the server permits it. */
  enabled: boolean
  /** Whether the server exposes the tool at all. */
  available: boolean
  approval_timeout_seconds: number
  /** Whether the server allows desktop control (open/close apps, power, etc.). */
  desktop_available: boolean
  /** Whether the server allows location lookups at all. */
  location_available: boolean
  /**
   * Which rung of the approval ladder the user is on. 1 Restricted, 2 Balanced,
   * 3 Trusted. The server is the only authority on this; the client never
   * decides what a level means, it renders what the server sent.
   */
  permission_level: number
  /**
   * The whole ladder, sent by the server so the names, ordering and wording
   * shown here are the same ones the gates enforce. Rendering a hard-coded copy
   * would let the two drift, which is exactly the kind of lie this UI must not
   * tell: a user who picks "Trusted" has to be shown what Trusted really means.
   */
  permission_levels: PermissionLevel[]
  /** The current rung's name, so a heading needs no lookup table. */
  permission_name: string
}

/** One rung of the approval ladder, as described by the server. */
export type PermissionLevel = {
  level: number
  name: string
  summary: string
  detail: string
}
