export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const API_BASE_KEY = 'pentagon.apiBase'

/**
 * The backend origin to talk to.
 *
 * Every request is a same-origin `/api/...` path, which the Vite dev server
 * proxies and the Electron main process forwards. The iOS and Android shells
 * have neither: their WebView loads from the bundle itself, so a relative path
 * would resolve to the device. Those builds therefore need an absolute origin,
 * set here from the saved preference or from the build-time default.
 */
export function getApiBase(): string {
  // Deliberately NOT VITE_API_BASE_URL: that names the address the dev server
  // proxies /api *to*, so reading it here would make the browser bypass the
  // proxy and call the backend cross-origin, which fails on CORS. This is the
  // origin the client itself dials, which only the packaged mobile shells need.
  //
  // `?.` collapses both "no key" and "empty string" to undefined, so clearing
  // the field restores the packaged default rather than pinning an empty origin.
  const saved = localStorage.getItem(API_BASE_KEY)?.trim()
  const fallback = String(import.meta.env.VITE_PENTAGON_API_BASE ?? '').trim()
  return (saved || fallback).replace(/\/+$/, '')
}

export function setApiBase(value: string): void {
  const trimmed = value.trim().replace(/\/+$/, '')
  if (trimmed) localStorage.setItem(API_BASE_KEY, trimmed)
  else localStorage.removeItem(API_BASE_KEY)
}

export function apiUrl(path: string): string {
  return `${getApiBase()}${path}`
}

/**
 * The backend's capability token.
 *
 * The desktop main process owns the secret and hands it over IPC; the page
 * never reads it off disk and it is never fetched over HTTP, so it cannot be
 * picked up by anything merely able to reach the API. Outside Electron (the
 * Vite dev server) there is no such bridge, so the build-time value is used.
 */
let capabilityOnce: Promise<string> | null = null

function getCapability(): Promise<string> {
  if (!capabilityOnce) {
    const bridge = (globalThis as { pentagon?: { capability?: () => Promise<string> } }).pentagon
    capabilityOnce = bridge?.capability
      ? bridge.capability().catch(() => '')
      : Promise.resolve(String(import.meta.env.VITE_PENTAGON_CAPABILITY ?? '').trim())
  }
  return capabilityOnce
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const capability = await getCapability()
  const headers = new Headers(init?.headers)
  if (capability) headers.set('X-Pentagon-Capability', capability)
  const response = await fetch(apiUrl(path), { ...init, headers })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: string | Array<{ msg?: string }> }
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) {
        message = body.detail.map((item) => item.msg).filter(Boolean).join(', ') || message
      }
    } catch { /* Keep the HTTP status when the body is not JSON. */ }
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function getLocalUserId(): string {
  // The desktop app hands down an id that lives on disk with the installation.
  // The packaged app serves itself from an ephemeral port, so its origin -- and
  // therefore its localStorage -- is new on every launch; trusting that would
  // hand the user a new identity, and a reset opt-in, each time they opened it.
  const installed = (globalThis as { pentagonUserId?: string }).pentagonUserId
  if (installed) return installed
  const key = 'pentagon.userId'
  const existing = localStorage.getItem(key)
  if (existing) return existing
  const id = `pentagon-${crypto.randomUUID()}`
  localStorage.setItem(key, id)
  return id
}

export function pcmToWavUrl(chunks: Uint8Array[], sampleRate: number, channels: number): string | null {
  const byteLength = chunks.reduce((total, chunk) => total + chunk.length, 0)
  if (!byteLength) return null
  const data = new Uint8Array(byteLength)
  let offset = 0
  for (const chunk of chunks) {
    data.set(chunk, offset)
    offset += chunk.length
  }
  const wav = new ArrayBuffer(44 + byteLength)
  const view = new DataView(wav)
  const write = (at: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(at + index, value.charCodeAt(index))
  }
  write(0, 'RIFF'); view.setUint32(4, 36 + byteLength, true); write(8, 'WAVE')
  write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true)
  view.setUint16(22, channels, true); view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * channels * 2, true); view.setUint16(32, channels * 2, true)
  view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, byteLength, true)
  new Uint8Array(wav, 44).set(data)
  return URL.createObjectURL(new Blob([wav], { type: 'audio/wav' }))
}
