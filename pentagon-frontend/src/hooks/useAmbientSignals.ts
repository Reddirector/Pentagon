import { useEffect } from 'react'
import { setAmbientSignal } from '../lib/ambient'

export interface UseAmbientSignalsOptions {
  streaming: boolean
  streamingWithContent: boolean
  transcribing: boolean
  uploading: boolean
  switching: boolean
  error: string
  composerFocused: boolean
  lastMessageHasContent: boolean
}

/**
 * The ambient layer reacts to what the app is actually doing: streaming,
 * thinking (a generic busy state), erroring, composer focus, and network
 * status. Kept in a hook so App's useEffect chain does not grow a seventh
 * or eighth entry just to keep the background reacting.
 */
export function useAmbientSignals(options: UseAmbientSignalsOptions): void {
  useEffect(() => {
    setAmbientSignal('streaming', options.streaming && options.streamingWithContent)
    setAmbientSignal('thinking', options.streaming || options.transcribing || options.uploading || options.switching)
    setAmbientSignal('error', Boolean(options.error))
    setAmbientSignal('focus', options.composerFocused)
    setAmbientSignal('offline', !navigator.onLine)
  }, [
    options.streaming,
    options.streamingWithContent,
    options.transcribing,
    options.uploading,
    options.switching,
    options.error,
    options.composerFocused,
    options.lastMessageHasContent,
  ])

  useEffect(() => {
    const sync = () => setAmbientSignal('offline', !navigator.onLine)
    window.addEventListener('online', sync)
    window.addEventListener('offline', sync)
    return () => {
      window.removeEventListener('online', sync)
      window.removeEventListener('offline', sync)
    }
  }, [])
}
