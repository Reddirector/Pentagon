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
import type { AutonomySettings, PendingApprovalsResponse, AuditLogEntry, Workflow, WorkflowRun } from './types'

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

export function getCapability(): Promise<string> {
  if (!capabilityOnce) {
    const bridge = (globalThis as { pentagon?: { capability?: () => Promise<string> } }).pentagon
    const fromStorage = typeof window !== 'undefined' ? localStorage.getItem('pentagon.capability')?.trim() : ''
    const envCapability = String(import.meta.env.VITE_PENTAGON_CAPABILITY ?? '').trim()
    capabilityOnce = bridge?.capability
      ? bridge.capability().catch(() => '')
      : Promise.resolve(fromStorage || envCapability)
  }
  return capabilityOnce
}

export function setCapability(token: string): void {
  const trimmed = token.trim()
  if (trimmed) localStorage.setItem('pentagon.capability', trimmed)
  else localStorage.removeItem('pentagon.capability')
  capabilityOnce = Promise.resolve(trimmed)
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const capability = await getCapability()
  const headers = new Headers(init?.headers)
  if (capability) headers.set('X-Pentagon-Capability', capability)
  if (typeof window !== 'undefined') {
    const nvidiaKey = localStorage.getItem('pentagon.nvidiaKey')?.trim()
    if (nvidiaKey && !headers.has('X-Nvidia-Key')) {
      headers.set('X-Nvidia-Key', nvidiaKey)
    }
  }
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

export type FilePreviewData = {
  id: string
  filename: string
  format: string
  media_type: string
  size: number
  preview: 'inline' | 'bytes' | 'image'
  text?: string
  image_data_url?: string
  download_url?: string
  truncated?: boolean
  sheets?: Array<{ name: string; rows: string[][] }>
  slides?: Array<{ slide_number: number; title: string; items: string[]; tables?: string[][][] }>
  docx_elements?: Array<{ kind: string; text?: string; rows?: string[][] }>
  pdf_pages?: string[]
  pdf_page_images?: string[]
  page_count?: number
}


export async function downloadGeneratedFile(fileId: string, filename: string): Promise<void> {
  const userId = getLocalUserId()
  const capability = await getCapability()
  const params = new URLSearchParams({ user_id: userId })
  if (capability) params.set('token', capability)
  const url = apiUrl(`/api/files/${encodeURIComponent(fileId)}/download?${params.toString()}`)

  const headers = new Headers()
  if (capability) headers.set('X-Pentagon-Capability', capability)
  const res = await fetch(url, { headers })
  if (!res.ok) throw new ApiError(`Download failed (${res.status})`, res.status)
  const blob = await res.blob()
  const blobUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(blobUrl), 2000)
}

export async function getFileBlobUrl(fileId: string): Promise<string> {
  const userId = getLocalUserId()
  const capability = await getCapability()
  const params = new URLSearchParams({ user_id: userId, inline: 'true' })
  if (capability) params.set('token', capability)
  const url = apiUrl(`/api/files/${encodeURIComponent(fileId)}/download?${params.toString()}`)

  const headers = new Headers()
  if (capability) headers.set('X-Pentagon-Capability', capability)
  const res = await fetch(url, { headers })
  if (!res.ok) throw new ApiError(`Failed to fetch file (${res.status})`, res.status)
  const buf = await res.arrayBuffer()
  const blob = new Blob([buf], { type: 'application/pdf' })
  return URL.createObjectURL(blob)
}

export async function fetchFilePreview(fileId: string): Promise<FilePreviewData> {
  const userId = getLocalUserId()
  return apiRequest<FilePreviewData>(`/api/files/${encodeURIComponent(fileId)}/preview?user_id=${encodeURIComponent(userId)}`)
}

export type WorkflowsResponse = {
  templates: Workflow[]
  workflows: Workflow[]
}

export async function fetchWorkflows(userId: string): Promise<WorkflowsResponse> {
  return apiRequest<WorkflowsResponse>(`/api/workflows?user_id=${encodeURIComponent(userId)}`)
}

export async function fetchWorkflow(id: string, userId: string): Promise<Workflow> {
  return apiRequest<Workflow>(`/api/workflows/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`)
}

export async function createWorkflow(data: {
  user_id: string
  name: string
  description?: string
  icon?: string
  category?: string
  nodes: any[]
  edges: any[]
}): Promise<Workflow> {
  return apiRequest<Workflow>('/api/workflows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function updateWorkflow(
  id: string,
  data: {
    user_id: string
    name?: string
    description?: string
    icon?: string
    category?: string
    nodes?: any[]
    edges?: any[]
  },
): Promise<Workflow> {
  return apiRequest<Workflow>(`/api/workflows/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function deleteWorkflow(id: string, userId: string): Promise<void> {
  await apiRequest(`/api/workflows/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
}

export async function runWorkflow(
  workflowId: string,
  userId: string,
  inputs: Record<string, any>,
): Promise<WorkflowRun> {
  return apiRequest<WorkflowRun>(`/api/workflows/${encodeURIComponent(workflowId)}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, inputs }),
  })
}

export async function fetchWorkflowRun(runId: string, userId: string): Promise<WorkflowRun> {
  return apiRequest<WorkflowRun>(`/api/workflows/runs/${encodeURIComponent(runId)}?user_id=${encodeURIComponent(userId)}`)
}

export async function fetchWorkflowRuns(workflowId: string, userId: string): Promise<{ runs: WorkflowRun[] }> {
  return apiRequest<{ runs: WorkflowRun[] }>(`/api/workflows/${encodeURIComponent(workflowId)}/runs?user_id=${encodeURIComponent(userId)}`)
}



