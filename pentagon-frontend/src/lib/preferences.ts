// Preferences that outlive a single render: appearance, contrast, the default
// model and the workspace name. Deliberately outside React so the theme can be
// written to <html> at module load, before the first paint, and so components
// can read it without prop-drilling.

export type Appearance = 'pitch' | 'graphite' | 'dusk'
export type Contrast = 'standard' | 'high'
export type Density = 'compact' | 'default' | 'relaxed'
export type TextSize = 'small' | 'default' | 'large'

export interface Preferences {
  appearance: Appearance
  contrast: Contrast
  density: Density
  textSize: TextSize
  workspaceName: string
  defaultModel: string
  /** Pixels, or 0 to follow the responsive breakpoint widths. */
  sidebarWidth: number
}

export const DENSITIES: { value: Density; label: string; note: string }[] = [
  { value: 'compact', label: 'Compact', note: 'Tighter rows and gaps. More threads per screen.' },
  { value: 'default', label: 'Default', note: 'The spacing this interface was designed around.' },
  { value: 'relaxed', label: 'Relaxed', note: 'More breathing room in lists, panels and controls.' },
]

export const TEXT_SIZES: { value: TextSize; label: string; note: string }[] = [
  { value: 'small', label: 'Small', note: 'Everything a little tighter, for dense screens.' },
  { value: 'default', label: 'Default', note: 'The size scale this interface was designed around.' },
  { value: 'large', label: 'Large', note: 'Bigger type throughout. Useful when the panel is small.' },
]

export const APPEARANCES: { value: Appearance; label: string; swatch: string; note: string }[] = [
  { value: 'pitch', label: 'Pitch', swatch: '#000000', note: 'True black. Maximum contrast with white type.' },
  { value: 'graphite', label: 'Graphite', swatch: '#0b0b0b', note: 'A softened black that reduces halation on OLED.' },
  { value: 'dusk', label: 'Dusk', swatch: '#141414', note: 'Lifted panels, easier on long reading sessions.' },
]

export const SIDEBAR_MIN_WIDTH = 200
export const SIDEBAR_MAX_WIDTH = 480
export const SIDEBAR_DEFAULT_WIDTH = 270

const DEFAULTS: Preferences = {
  appearance: 'pitch',
  contrast: 'standard',
  density: 'default',
  textSize: 'default',
  workspaceName: 'Personal workspace',
  defaultModel: '',
  sidebarWidth: 0,
}

function clampSidebarWidth(value: unknown): number {
  const parsed = typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : 0
  // 0 means "use the breakpoint default", so it must survive as-is.
  if (parsed === 0) return 0
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, parsed))
}

const STORE_KEY = 'pentagon.preferences'

function isDensity(value: unknown): value is Density {
  return value === 'compact' || value === 'default' || value === 'relaxed'
}

function isTextSize(value: unknown): value is TextSize {
  return value === 'small' || value === 'default' || value === 'large'
}

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
      density: isDensity(parsed.density) ? parsed.density : DEFAULTS.density,
      textSize: isTextSize(parsed.textSize) ? parsed.textSize : DEFAULTS.textSize,
      workspaceName: typeof parsed.workspaceName === 'string' && parsed.workspaceName.trim()
        ? parsed.workspaceName.trim().slice(0, 40)
        : DEFAULTS.workspaceName,
      defaultModel: typeof parsed.defaultModel === 'string' ? parsed.defaultModel : '',
      sidebarWidth: clampSidebarWidth(parsed.sidebarWidth),
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
  root.dataset.density = current.density
  root.dataset.textSize = current.textSize
}

function commit(next: Partial<Preferences>) {
  const merged = { ...current, ...next }
  if (merged.workspaceName.trim()) merged.workspaceName = merged.workspaceName.trim().slice(0, 40)
  if (
    merged.appearance === current.appearance &&
    merged.contrast === current.contrast &&
    merged.density === current.density &&
    merged.textSize === current.textSize &&
    merged.workspaceName === current.workspaceName &&
    merged.defaultModel === current.defaultModel &&
    merged.sidebarWidth === current.sidebarWidth
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

export function setDensity(density: Density) {
  commit({ density })
}

export function setTextSize(textSize: TextSize) {
  commit({ textSize })
}

export function setWorkspaceName(workspaceName: string) {
  commit({ workspaceName })
}

export function setDefaultModel(defaultModel: string) {
  commit({ defaultModel })
}

/** Pass 0 to hand the width back to the responsive breakpoint defaults. */
export function setSidebarWidth(sidebarWidth: number) {
  commit({ sidebarWidth: clampSidebarWidth(sidebarWidth) })
}

export function resetPreferences() {
  current = DEFAULTS
  persist()
  applyToDocument()
  for (const listener of listeners) listener()
}

// Applied at import time so a reload never flashes the previous theme.
applyToDocument()