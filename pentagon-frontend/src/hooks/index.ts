/**
 * Hooks extracted from App.tsx during the maintainability decomposition.
 *
 * Each hook owns exactly one slice of the component's original state and
 * entitlements. Nothing behavioural moved: this module is the same code, cut
 * along its seams, so App can read as composition rather than as a 1,700-line
 * ledger.
 */

export { useApiKeys } from './useApiKeys'
export { useCommandSettings } from './useCommandSettings'
export { useAutonomy } from './useAutonomy'
export { useAgentBadges } from './useAgentBadges'
export { usePendingApprovals, usePendingCommands } from './usePendingApprovals'
export { useAudioUrls } from './useAudioUrls'
export { useAmbientSignals } from './useAmbientSignals'
export { useKeyboardShortcuts } from './useKeyboardShortcuts'
export { useChatStream } from './useChatStream'
export type { UseChatStreamOptions, GeneratedFileInfo } from './useChatStream'
