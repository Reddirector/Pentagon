// Preferences that outlive a single render: appearance, contrast, the default
// model and the workspace name. Deliberately outside React so the theme can be
// written to <html> at module load, before the first paint, and so components
// can read it without prop-drilling.

export type Appearance = 'pitch' | 'graphite' | 'dusk'
export type Contrast = 'standard' | 'high'

export interface Preferences {
  appearance: Appearance
  contrast: Contrast
  workspaceName: string
  defaultModel: string
}

export const APPEARANCES: { value: Appearance; label: string; swatch: string; note: string }[] = [
  { value: 'pitch', label: 'Pitch', swatch: '#000000', note: 'True black. Maximum contrast with white type.' },
  { value: 'graphite', label: 'Graphite', swatch: '#0b0b0b', note: 'A softened black that reduces halation on OLED.' },
  { value: 'dusk', label: 'Dusk', swatch: '#141414', note: 'Lifted panels, easier on long reading sessions.' },
]

const DEFAULTS: Preferences = {
  appearance: 'pitch',
  contrast: 'standard',
  workspaceName: 'Personal workspace',
  defaultModel: '',
}

const STORE_KEY = 'pentagon.preferences'

function isAppearance(value: unknown): value is Appearance {
  return value === 'pitch' || value === 'graphite' || value === 'dusk'
}

function read(): Preferences {
  try {
    const raw = window.localStorage.getItem(STORE_KEY)
    if (!raw) return DEFAULTS
    const parsed = JSON.parse(raw) as Partial<Preferences>
    return {
      appearance: isAppearance(parsed.appearance) ? parsed.appearance : DEFAULTS.appearance,
      contrast: parsed.contrast === 'high' ? 'high' : 'standard',
      workspaceName: typeof parsed.workspaceName === 'string' && parsed.workspaceName.trim()
        ? parsed.workspaceName.trim().slice(0, 40)
        : DEFAULTS.workspaceName,
      defaultModel: typeof parsed.defaultModel === 'string' ? parsed.defaultModel : '',
    }
  } catch {
    return DEFAULTS
  }
}

// Replaced wholesale rather than mutated: useSyncExternalStore compares the
// snapshot by identity, so mutating in place would not notify subscribers.
let current: Preferences = read()
const listeners = new Set<() => void>()

function persist() {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(current))
  } catch {
    /* Private browsing can refuse writes; the in-memory value still applies. */
  }
}

/** Reflect the preferences onto <html>, where index.css reads them. */
function applyToDocument() {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.appearance = current.appearance
  root.dataset.contrast = current.contrast
}

function commit(next: Partial<Preferences>) {
  const merged = { ...current, ...next }
  if (merged.workspaceName.trim()) merged.workspaceName = merged.workspaceName.trim().slice(0, 40)
  if (
    merged.appearance === current.appearance &&
    merged.contrast === current.contrast &&
    merged.workspaceName === current.workspaceName &&
    merged.defaultModel === current.defaultModel
  ) return
  current = merged
  persist()
  applyToDocument()
  for (const listener of listeners) listener()
}

export function subscribePreferences(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getPreferences(): Preferences {
  return current
}

export function setAppearance(appearance: Appearance) {
  commit({ appearance })
}

export function setContrast(contrast: Contrast) {
  commit({ contrast })
}

export function setWorkspaceName(workspaceName: string) {
  commit({ workspaceName })
}

export function setDefaultModel(defaultModel: string) {
  commit({ defaultModel })
}

export function resetPreferences() {
  current = DEFAULTS
  persist()
  applyToDocument()
  for (const listener of listeners) listener()
}

// Applied at import time so a reload never flashes the previous theme.
applyToDocument()