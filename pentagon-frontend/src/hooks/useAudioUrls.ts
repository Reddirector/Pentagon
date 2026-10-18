import { useCallback, useEffect, useRef } from 'react'

export interface UseAudioUrls {
  /** Register a freshly-created object URL so it can be revoked later. */
  track: (url: string) => void
}

/**
 * Object URLs for synthesised replies. A WAV is megabytes, and handing out a
 * fresh one per answer nothing ever released grew without bound over a long
 * session with speech. Registered on creation; revoked once no live message
 * points at them, and on unmount.
 */
export function useAudioUrls(messages: { audioUrl?: string }[]): UseAudioUrls {
  const urls = useRef<Set<string>>(new Set())

  const track = useCallback((url: string) => {
    urls.current.add(url)
  }, [])

  useEffect(() => {
    const live = new Set(messages.map((item) => item.audioUrl).filter((url): url is string => Boolean(url)))
    for (const url of urls.current) {
      if (live.has(url)) continue
      URL.revokeObjectURL(url)
      urls.current.delete(url)
    }
  }, [messages])

  useEffect(() => () => {
    for (const url of urls.current) URL.revokeObjectURL(url)
    urls.current.clear()
  }, [])

  return { track }
}
