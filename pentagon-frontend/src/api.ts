export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const API_BASE_KEY = 'pentagon.apiBase'

// Local-forward declarations so api.ts can be imported without its own type file.
// (types.ts is the canonical source; these exist to keep api.ts self-contained.)
import type { AutonomySettings, PendingApprovalsResponse, AuditLogEntry } from './types'

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

/** Per-category autonomy settings for the current user. */
export async function fetchAutonomySettings(userId: string): Promise<AutonomySettings> {
  return apiRequest<AutonomySettings>('/api/autonomy-settings?user_id=' + encodeURIComponent(userId))
}

/** Update one category's autonomy level. */
export async function putAutonomySetting(
  userId: string,
  category: string,
  level: string,
): Promise<{ status: string; category: string; level: string }> {
  return apiRequest<{ status: string; category: string; level: string }>(
    '/api/autonomy-settings/' + encodeURIComponent(category),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, level }),
    },
  )
}

/** Apply a preset across all six categories. */
export async function applyAutonomyPreset(
  userId: string,
  preset: string,
): Promise<AutonomySettings> {
  const current = await fetchAutonomySettings(userId)
  const presetDef = current.presets[preset]
  if (!presetDef) throw new Error('Unknown preset: ' + preset)
  for (const [category, level] of Object.entries(presetDef.levels)) {
    await putAutonomySetting(userId, category, level)
  }
  return fetchAutonomySettings(userId)
}

/** Pending approvals for a conversation. */
export async function fetchPendingApprovals(
  userId: string,
  conversationId: string,
): Promise<PendingApprovalsResponse> {
  return apiRequest<PendingApprovalsResponse>(
    '/api/pending-approvals?user_id=' + encodeURIComponent(userId)
    + '&conversation_id=' + encodeURIComponent(conversationId),
  )
}

/** Approve a pending approval and resume the graph. */
export async function approvePendingApproval(
  approvalId: string,
  userId: string,
): Promise<{ status: string; id: string }> {
  return apiRequest<{ status: string; id: string }>(
    '/api/pending-approvals/' + encodeURIComponent(approvalId) + '/approve',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, decision: 'approved', approved_this_session: true }),
    },
  )
}

/** Deny a pending approval and resume the graph. */
export async function denyPendingApproval(
  approvalId: string,
  userId: string,
): Promise<{ status: string; id: string }> {
  return apiRequest<{ status: string; id: string }>(
    '/api/pending-approvals/' + encodeURIComponent(approvalId) + '/deny',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, decision: 'denied', approved_this_session: false }),
    },
  )
}

/** Paginated audit log. */
export async function fetchAuditLog(
  userId: string,
  limit = 100,
  before?: string,
  category?: string,
  decision?: string,
): Promise<{ rows: AuditLogEntry[]; limit: number }> {
  const params = new URLSearchParams({ user_id: userId, limit: String(limit) })
  if (before) params.set('before', before)
  if (category) params.set('category', category)
  if (decision) params.set('decision', decision)
  return apiRequest<{ rows: AuditLogEntry[]; limit: number }>('/api/audit-log?' + params.toString())
}


