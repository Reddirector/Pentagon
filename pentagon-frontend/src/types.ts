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
  image_path?: string | null
  attachmentName?: string
  execution_trace?: ExecutionTrace
  sources_used?: SourcesUsed
  audioUrl?: string
}

export type DocumentInfo = {
  document_id: string
  filename: string
  chunks_stored: number
  created_at?: string
}
