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
    const trimmed = keyValue.trim()
    if (!trimmed) return

    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      if (!trimmed.startsWith('nvapi-') || trimmed.length < 10) {
        setKeyValidation('invalid')
        setKeyValidationMessage('Key must start with nvapi-')
        return
      }
      try {
        const result = await apiRequest<{ valid: boolean; reason?: string }>('/api/keys/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: trimmed }),
          signal: controller.signal,
        })
        setKeyValidation(result.valid ? 'valid' : 'invalid')
        setKeyValidationMessage(result.valid ? 'Key verified' : result.reason || 'Key not accepted')
      } catch (cause) {
        if (controller.signal.aborted) return
        // Direct browser check against NVIDIA models endpoint as reliable fallback
        try {
          const directRes = await fetch('https://integrate.api.nvidia.com/v1/models', {
            headers: { Authorization: `Bearer ${trimmed}` },
            signal: controller.signal,
          })
          if (directRes.ok) {
            setKeyValidation('valid')
            setKeyValidationMessage('Key verified')
            return
          } else if (directRes.status === 401 || directRes.status === 403) {
            setKeyValidation('invalid')
            setKeyValidationMessage('Key rejected by NVIDIA')
            return
          }
        } catch {
          // Direct fetch failed
        }
        setKeyValidation('invalid')
        const message = cause instanceof Error ? cause.message : 'Validation failed'
        setKeyValidationMessage(message.includes('404') || message.includes('fetch') ? 'Could not reach server' : message)
      }
    }, 450)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [keyValue])

  const saveKey = useCallback(async (event: FormEvent) => {
    event.preventDefault()
    if (keyValidation !== 'valid' || savingKey) return
    setSavingKey(true)
    setError('')
    try {
      const trimmed = keyValue.trim()
      localStorage.setItem('pentagon.nvidiaKey', trimmed)
      try {
        await apiRequest('/api/keys', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, api_key: trimmed }),
        })
      } catch {
        // Saved locally in browser storage
      }
      setKeyValue('')
      setKeyValidation('idle')
      window.location.reload()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save key')
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
