/**
 * The Advanced tab's Appearance and Model sections: pure preference widgets
 * reading the shared preferences store.
 */
import { useSyncExternalStore } from 'react'
import { MoonStar, Sun, Waves } from 'lucide-react'
import {
  APPEARANCES,
  DENSITIES,
  TEXT_SIZES,
  getPreferences,
  setAppearance,
  setContrast,
  setDefaultModel,
  setDensity,
  setSidebarCollapsed,
  setTextSize,
  subscribePreferences,
} from '../../../lib/preferences'
import type { Appearance, Contrast, Density, TextSize } from '../../../lib/preferences'
import { getAmbientMode, setAmbientMode, subscribeAmbient } from '../../../lib/ambient'
import type { AmbientMode } from '../../../lib/ambient'
import type { ModelInfo } from '../../../types'
import { Choice, Section, selectClass } from '../shared'

const AMBIENT_OPTIONS: { mode: AmbientMode; label: string; description: string; icon: typeof Sun }[] = [
  { mode: 'full', label: 'Full', description: 'Aurora, orbit rings, a twinkling constellation, grain and a vignette.', icon: Sun },
  { mode: 'calm', label: 'Calm', description: 'Half the stars, slower drift, no long rotations.', icon: Waves },
  { mode: 'off', label: 'Off', description: 'A plain static background. Nothing moves.', icon: MoonStar },
]

export function AppearanceSection() {
  // Subscribed rather than read once, so the ambient radio repaints when the
  // mode changes (including the session-only auto-downgrade).
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  const ambientMode = useSyncExternalStore(subscribeAmbient, getAmbientMode)

  return (
    <>
      <Section title="Background" hint="Monochrome by design. Surfaces shift, the palette does not.">
        <div role="radiogroup" aria-label="Background" className="grid gap-2">
          {APPEARANCES.map((option) => (
            <Choice
              key={option.value}
              selected={prefs.appearance === option.value}
              onSelect={() => setAppearance(option.value as Appearance)}
              label={option.label}
              note={option.note}
              swatch={option.swatch}
            />
          ))}
        </div>
      </Section>

      <Section title="Contrast" hint="Lifts the dim greys used for secondary text.">
        <div role="radiogroup" aria-label="Contrast" className="grid gap-2 sm:grid-cols-2">
          <Choice
            selected={prefs.contrast === 'standard'}
            onSelect={() => setContrast('standard' as Contrast)}
            label="Standard"
            note="Tuned for pure black; secondary text clears WCAG AA."
          />
          <Choice
            selected={prefs.contrast === 'high'}
            onSelect={() => setContrast('high' as Contrast)}
            label="High"
            note="Brighter dim text for dim rooms or low-quality panels."
          />
        </div>
      </Section>

      <Section title="Text size" hint="Rescales the whole type scale, from thread titles to body copy.">
        <div role="radiogroup" aria-label="Text size" className="grid gap-2 sm:grid-cols-3">
          {TEXT_SIZES.map((option) => (
            <Choice
              key={option.value}
              selected={prefs.textSize === option.value}
              onSelect={() => setTextSize(option.value as TextSize)}
              label={option.label}
              note={option.note}
            />
          ))}
        </div>
      </Section>

      <Section title="Density" hint="Tightens or loosens every gap and inset in the interface.">
        <div role="radiogroup" aria-label="Density" className="grid gap-2 sm:grid-cols-3">
          {DENSITIES.map((option) => (
            <Choice
              key={option.value}
              selected={prefs.density === option.value}
              onSelect={() => setDensity(option.value as Density)}
              label={option.label}
              note={option.note}
            />
          ))}
        </div>
      </Section>

      <Section title="Sidebar" hint="Folds the thread list away to icons, or shows it in full. Also toggleable with ⌘B / Ctrl+B.">
        <div role="radiogroup" aria-label="Sidebar" className="grid gap-2 sm:grid-cols-2">
          <Choice
            selected={!prefs.sidebarCollapsed}
            onSelect={() => setSidebarCollapsed(false)}
            label="Expanded"
            note="Thread titles, dates and the search field."
          />
          <Choice
            selected={prefs.sidebarCollapsed}
            onSelect={() => setSidebarCollapsed(true)}
            label="Collapsed"
            note="An icon rail. Hover a thread for its title."
          />
        </div>
      </Section>

      <Section title="Ambient effects" hint="The animated backdrop behind the conversation.">
        <div role="radiogroup" aria-label="Ambient background intensity" className="grid gap-2">
          {AMBIENT_OPTIONS.map((option) => (
            <Choice
              key={option.mode}
              selected={ambientMode === option.mode}
              onSelect={() => setAmbientMode(option.mode)}
              label={option.label}
              note={option.description}
              icon={option.icon}
            />
          ))}
        </div>
      </Section>
    </>
  )
}

export function DefaultModelSection({
  models,
  serverDefaultModel,
}: {
  models: ModelInfo[]
  serverDefaultModel: string
}) {
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  return (
    <Section
      title="Default model"
      hint="Used for new threads. An existing thread keeps the model it was started with."
    >
      <div className="space-y-2.5">
        <select
          value={prefs.defaultModel || ''}
          onChange={(event) => setDefaultModel(event.target.value)}
          className={selectClass}
          aria-label="Default model"
        >
          <option value="" className="bg-black text-white">
            Server default{serverDefaultModel ? ` (${serverDefaultModel})` : ''}
          </option>
          {models.map((model) => (
            <option key={model.id} value={model.id} className="bg-black text-white">
              {model.id}
            </option>
          ))}
        </select>
        <p className="text-small leading-[1.6] text-zinc-600">
          {models.length} model{models.length === 1 ? '' : 's'} available on this server. Reasoning models can take
          a couple of minutes before the first token.
        </p>
      </div>
    </Section>
  )
}
