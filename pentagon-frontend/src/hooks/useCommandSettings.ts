import { useCallback, useState } from 'react'
import { apiRequest } from '../api'
import type { CommandSettings } from './types/app'

export interface UseCommandSettings {
  commandSettings: CommandSettings
  setCommandSettings: React.Dispatch<React.SetStateAction<CommandSettings>>
  loadCommandSettings: () => Promise<void>
}

const FALLBACK: CommandSettings = {
  enabled: false,
  available: false,
  approval_timeout_seconds: 300,
  desktop_available: false,
  location_available: false,
  permission_level: 2,
  permission_levels: [],
  permission_name: 'Balanced',
}

/**
 * The shell tool's settings, one fetch at bootstrap. A server without the
 * tool simply reports nothing: the toggle stays off rather than the app
 * failing to start.
 */
export function useCommandSettings(userId: string): UseCommandSettings {
  const [commandSettings, setCommandSettings] = useState<CommandSettings>(FALLBACK)

  const loadCommandSettings = useCallback(async () => {
    try {
      const result = await apiRequest<CommandSettings>(
        `/api/commands/settings?user_id=${encodeURIComponent(userId)}`,
      )
      setCommandSettings(result)
    } catch {
      setCommandSettings(FALLBACK)
    }
  }, [userId])

  return { commandSettings, setCommandSettings, loadCommandSettings }
}
