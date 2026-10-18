import { useCallback, useState } from 'react'
import { apiRequest } from '../api'

export interface UseAgentBadges {
  badges: Record<string, { badge: string }>
  refresh: () => Promise<void>
}

/**
 * Capability badges come from the server's probe cache — a plain GET, no
 * network beyond our own backend — so the header can say how a model
 * tool-calls without spending anything to find out. A failed read leaves
 * badges absent, never wrong: it is decoration, not state the product
 * depends on.
 */
export function useAgentBadges(): UseAgentBadges {
  const [badges, setBadges] = useState<Record<string, { badge: string }>>({})

  const refresh = useCallback(async () => {
    try {
      const data = await apiRequest<Record<string, { badge: string }>>('/api/agent/badges', { method: 'GET' })
      setBadges(data ?? {})
    } catch {
      /* Decoration: a failed read leaves badges absent, never wrong. */
    }
  }, [])

  return { badges, refresh }
}
