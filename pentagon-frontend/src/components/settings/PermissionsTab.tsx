/**
 * The Permissions top tab: the default-model picker and the autonomy panel.
 * Both handlers wrap the dialog's own API calls exactly as before; the
 * component is pure composition, so no state moved into it.
 */
import { useSyncExternalStore, useState } from 'react'
import {
  getPreferences,
  setDefaultModel,
  subscribePreferences,
} from '../../lib/preferences'
import type { AutonomySettings, ModelInfo } from '../../types'
import { Search } from 'lucide-react'
import { PermissionPanel } from '../PermissionPanel'
import { applyAutonomyPreset, putAutonomySetting } from '../../api'
import { Section, selectClass } from './shared'

export function PermissionsTab({
  userId,
  models,
  serverDefaultModel,
  autonomySettings,
  onAutonomySettingChange,
  onAutonomyPresetChange,
}: {
  userId: string
  models: ModelInfo[]
  serverDefaultModel: string
  autonomySettings: AutonomySettings | null
  onAutonomySettingChange?: (category: string, level: string) => void | Promise<void>
  onAutonomyPresetChange?: (preset: string) => void | Promise<void>
}) {
  const prefs = useSyncExternalStore(subscribePreferences, getPreferences)
  const [busy, setBusy] = useState(false)

  async function handleCategoryChange(category: string, level: string) {
    if (!onAutonomySettingChange) return
    setBusy(true)
    try {
      await putAutonomySetting(userId, category, level)
      await onAutonomySettingChange(category, level)
    } catch {
      // Best-effort: the parent re-fetches settings on change, so a failed
      // write does not leave the panel stale.
    } finally {
      setBusy(false)
    }
  }

  async function handlePresetChange(preset: string) {
    if (!onAutonomyPresetChange) return
    setBusy(true)
    try {
      const next = await applyAutonomyPreset(userId, preset)
      await onAutonomyPresetChange(preset)
      // Refresh local copy so the panel shows the freshly saved state.
      if (onAutonomySettingChange) {
        for (const [category, level] of Object.entries(next.settings as Record<string, string>)) {
          await onAutonomySettingChange(category, level)
        }
      }
    } catch {
      // Best-effort: the parent re-fetches settings on change.
    } finally {
      setBusy(false)
    }
  }

  const [modelSearch, setModelSearch] = useState('')
  const filteredModels = modelSearch.trim()
    ? models.filter((m) => m.id.toLowerCase().includes(modelSearch.trim().toLowerCase()))
    : models

  return (
    <>
      <Section
        title="Default model"
        hint="Used for new threads. An existing thread keeps the model it was started with."
      >
        <div className="space-y-2.5">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <input
              type="text"
              value={modelSearch}
              onChange={(e) => setModelSearch(e.target.value)}
              placeholder="Search default models..."
              className="h-8 w-full rounded-lg border border-white/[0.08] bg-white/[0.02] pl-8 pr-3 text-caption text-zinc-200 placeholder:text-zinc-600 focus:border-emerald-500/40 focus:outline-none"
            />
          </div>

          <select
            value={prefs.defaultModel || ''}
            onChange={(event) => setDefaultModel(event.target.value)}
            className={selectClass}
            aria-label="Default model"
          >
            <option value="" className="bg-black text-white">
              Server default{serverDefaultModel ? ` (${serverDefaultModel})` : ''}
            </option>
            {filteredModels.map((model) => (
              <option key={model.id} value={model.id} className="bg-black text-white">
                {model.id}
              </option>
            ))}
          </select>
          <p className="text-small leading-[1.6] text-zinc-600">
            {filteredModels.length} of {models.length} model{models.length === 1 ? '' : 's'} available on this server. Reasoning models can take
            a couple of minutes before the first token.
          </p>
        </div>
      </Section>
      {autonomySettings ? (
        <PermissionPanel
          settings={autonomySettings}
          busy={busy}
          onChange={(category, level) => void handleCategoryChange(category, level)}
          onPresetChange={onAutonomyPresetChange ? (preset) => void handlePresetChange(preset) : undefined}
        />
      ) : (
        <p className="text-small text-zinc-500">Loading permissions…</p>
      )}
    </>
  )
}
