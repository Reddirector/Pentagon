import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, apiRequest } from '../api'
import type { Validation } from './types/app'

export interface UseApiKeys {
  keyValue: string
  keyValidation: Validation
  keyValidationMessage: string
  savingKey: boolean
  error: string
  setError: (next: string) => void
  setKeyValue: (next: string) => void
  setKeyValidation: (next: Validation) => void
  setKeyValidationMessage: (next: string) => void
  saveKey: (event: FormEvent) => Promise<void>
}

/**
 * The NVIDIA-key gate: everything a fresh browser needs before the app can
 * list models. A key is debounced to /api/keys/validate, then stored via
 * /api/keys, which sends the app into a full reload because almost every
 * loaded bit (models, threads, badges) depends on the key that just changed.
 */
export function useApiKeys(userId: string): UseApiKeys {
  const [keyValue, setKeyValue] = useState('')
  const [keyValidation, setKeyValidation] = useState<Validation>('idle')
  const [keyValidationMessage, setKeyValidationMessage] = useState('Enter a key to validate it with NVIDIA.')
  const [savingKey, setSavingKey] = useState(false)
  const [error, setError] = useState('')

  // Debounced live validation. Aborted on change so typing `sk-a` + `sk-ab`
  // does not send stale responses out of order.
  useEffect(() => {
    if (!keyValue.trim()) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const result = await apiRequest<{ valid: boolean; reason?: string }>('/api/keys/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: keyValue }),
          signal: controller.signal,
        })
        setKeyValidation(result.valid ? 'valid' : 'invalid')
        setKeyValidationMessage(result.valid ? 'Key verified and ready to save.' : result.reason || 'NVIDIA did not accept this key.')
      } catch (cause) {
        if (controller.signal.aborted) return
        setKeyValidation('invalid')
        setKeyValidationMessage(cause instanceof Error ? cause.message : 'Key validation failed.')
      }
    }, 500)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [keyValue])

  const saveKey = useCallback(async (event: FormEvent) => {
    event.preventDefault()
    // The gate never saves an unvalidated key: the button is disabled too, but
    // a race between keystroke and disable could otherwise slip one through.
    if (keyValidation !== 'valid' || savingKey) return
    setSavingKey(true)
    setError('')
    try {
      await apiRequest('/api/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, api_key: keyValue }),
      })
      setKeyValue('')
      setKeyValidation('idle')
      setKeyValidationMessage('Enter a key to validate it with NVIDIA.')
      // A full reload is the cheapest correct invalidation: the key change
      // invalidates the model catalog, the default model choice, badges and
      // command settings at once. Keeping the old page loaded would leave
      // stale values visible until the user next interacted.
      window.location.reload()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not store the NVIDIA key.')
    } finally {
      setSavingKey(false)
    }
  }, [keyValidation, savingKey, keyValue, userId])

  return {
    keyValue,
    keyValidation,
    keyValidationMessage,
    savingKey,
    error,
    setError,
    setKeyValue,
    setKeyValidation,
    setKeyValidationMessage,
    saveKey,
  }
}

// Kept local to the hook file because only the above uses it — ApiError was
// imported by the original component purely to detect a 404 during hydrate.
export type { ApiError as ApiErrorType }
