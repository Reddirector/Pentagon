import { useCallback, useState } from 'react'
import {
  applyAutonomyPreset,
  fetchAutonomySettings,
  putAutonomySetting,
} from '../api'
import type { AutonomySettings } from './types/app'

export interface UseAutonomy {
  autonomySettings: AutonomySettings | null
  busy: boolean
  load: () => Promise<void>
  changeSetting: (category: string, level: string) => Promise<void>
  changePreset: (preset: string) => Promise<void>
}

/**
 * The autonomy panel's state and actions. The per-category setters delegate
 * to the API and then refresh the local snapshot so the six rows always show
 * what the server accepted, not what the client optimistically hoped for.
 */
export function useAutonomy(userId: string): UseAutonomy {
  const [autonomySettings, setAutonomySettings] = useState<AutonomySettings | null>(null)
  const [busy, setBusy] = useState(false)

  // A server without the autonomy system returns nothing; the panel shows
  // the fallback empty state rather than crashing.
  const load = useCallback(async () => {
    try {
      const settings = await fetchAutonomySettings(userId)
      setAutonomySettings(settings)
    } catch {
      setAutonomySettings(null)
    }
  }, [userId])

  const changeSetting = useCallback(async (category: string, level: string) => {
    setBusy(true)
    try {
      await putAutonomySetting(userId, category, level)
      await load()
    } finally {
      setBusy(false)
    }
  }, [userId, load])

  const changePreset = useCallback(async (preset: string) => {
    setBusy(true)
    try {
      await applyAutonomyPreset(userId, preset)
      await load()
    } finally {
      setBusy(false)
    }
  }, [userId, load])

  return { autonomySettings, busy, load, changeSetting, changePreset }
}
