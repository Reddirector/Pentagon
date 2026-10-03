export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
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
