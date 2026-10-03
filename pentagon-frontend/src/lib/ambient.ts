// Ambient background store: passive visual layers driven by app state.
// Kept in a module (not React state) so the canvas loop can update it at 30fps
// without triggering component re-renders on every frame.

export type AmbientState =
  | 'idle'
  | 'focus'
  | 'thinking'
  | 'streaming'
  | 'approval'
  | 'error'
  | 'offline'

export type AmbientMode = 'full' | 'calm' | 'off'

// Highest priority wins when several conditions are active at once.
const PRIORITY: AmbientState[] = [
  'approval',
  'offline',
  'error',
  'thinking',
  'streaming',
  'focus',
  'idle',
]

const MODE_KEY = 'pentagon.ambientMode'

function detectDefaultMode(): AmbientMode {
  if (typeof window === 'undefined') return 'calm'
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 'off'
  const nav = navigator as Navigator & { deviceMemory?: number }
  const cores = nav.hardwareConcurrency ?? 8
  const memory = nav.deviceMemory ?? 8
  if (cores <= 4 || memory <= 4) return 'calm'
  return 'full'
}

function readStoredMode(): AmbientMode | null {
  try {
    const raw = window.localStorage.getItem(MODE_KEY)
    return raw === 'full' || raw === 'calm' || raw === 'off' ? raw : null
  } catch {
    return null
  }
}

function writeStoredMode(mode: AmbientMode) {
  try {
    window.localStorage.setItem(MODE_KEY, mode)
  } catch {
    /* Private browsing can refuse writes; the in-memory mode still applies. */
  }
}

let mode: AmbientMode = readStoredMode() ?? detectDefaultMode()
// Session-only downgrade from the frame-time auto-guard. Never persisted.
let autoDowngrades = 0
// Conditions are tracked independently and the highest-priority active one
// wins. Reporting "no longer streaming" must clear the state, so a plain
// "set next state" would strand us in 'thinking' forever.
const signals = new Set<AmbientState>()
const listeners = new Set<() => void>()

function resolveState(): AmbientState {
  for (const candidate of PRIORITY) {
    if (signals.has(candidate)) return candidate
  }
  return 'idle'
}

let state: AmbientState = 'idle'

function emit() {
  for (const listener of listeners) listener()
}

export function subscribeAmbient(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getAmbientState() {
  return state
}

export function getAmbientMode() {
  return mode
}

/** Turn a condition on or off; the resolved state follows the priority list. */
export function setAmbientSignal(signal: AmbientState, active: boolean) {
  if (active) signals.add(signal)
  else signals.delete(signal)
  const next = resolveState()
  if (next === state) return
  state = next
  emit()
}

export function setAmbientMode(next: AmbientMode) {
  mode = next
  autoDowngrades = 0
  writeStoredMode(next)
  emit()
}

/**
 * Auto-guard: sustained slow frames mean the ambient layer is costing more than
 * it is worth. Drop one level for this session only, silently.
 */
export function applyAutoDowngrade() {
  if (autoDowngrades >= 2 || mode === 'off') return
  autoDowngrades += 1
  mode = mode === 'full' ? 'calm' : 'off'
  emit()
}

export function dotCount(mode: AmbientMode, area: number) {
  if (mode === 'off') return 0
  const scaled = Math.round(Math.min(90, Math.max(24, area / 9000)))
  return mode === 'calm' ? Math.round(scaled / 2) : scaled
}