/**
 * App-level shared types extracted from App.tsx during the decomposition.
 * The canonical definitions live in `src/types.ts`; this module re-exports
 * them (plus the two App-only aliases) so hooks and component slices can
 * import without App itself becoming a dependency of smaller leaves.
 */
import type {
  AgentPlanStep,
  AutonomySettings,
  ChatMessage,
  CommandRun,
  CommandSettings,
  Conversation,
  DocumentInfo,
  ExecutionTrace,
  ModelInfo,
  PendingApproval,
  PendingCommand,
  PendingToolApproval,
  SourcesUsed,
  Verification,
} from '../../types'

export type ConversationDetail = Conversation & {
  messages: ChatMessage[]
  summary_at_switch: string | null
}

export type TranscriptInfo = { durationMs: number; provider: string }

export type Validation = 'idle' | 'checking' | 'valid' | 'invalid'

export type {
  AgentPlanStep,
  AutonomySettings,
  ChatMessage,
  CommandRun,
  CommandSettings,
  Conversation,
  DocumentInfo,
  ExecutionTrace,
  ModelInfo,
  PendingApproval,
  PendingCommand,
  PendingToolApproval,
  SourcesUsed,
  Verification,
}
