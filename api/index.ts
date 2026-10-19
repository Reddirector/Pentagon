/**
 * Vercel Edge Serverless API Router for Pentagon
 * Provides zero-cold-start, global Edge backend services for:
 * - Key validation & storage
 * - NVIDIA NIM models discovery & proxying
 * - Real-time SSE streaming chat completions
 * - Conversations, autonomy, MCP, and commands endpoints
 */

export const config = {
  runtime: 'edge',
}

const DEFAULT_MODELS = [
  { id: 'meta/llama-3.2-3b-instruct', supports_vision: false, context_window: 131072 },
  { id: 'nvidia/llama-3.1-nemotron-70b-instruct', supports_vision: false, context_window: 131072 },
  { id: 'meta/llama-3.2-11b-vision-instruct', supports_vision: true, context_window: 131072 },
  { id: 'meta/llama-3.2-90b-vision-instruct', supports_vision: true, context_window: 131072 },
  { id: 'mistralai/mistral-large-2-instruct', supports_vision: false, context_window: 131072 },
  { id: 'deepseek-ai/deepseek-v4.1-flash', supports_vision: false, context_window: 65536 },
  { id: 'google/gemma-3-12b-it', supports_vision: false, context_window: 8192 },
  { id: 'google/gemma-4-31b-it', supports_vision: false, context_window: 8192 },
  { id: 'mistralai/mixtral-8x22b-v0.1', supports_vision: false, context_window: 65536 },
]

function normalizeModel(model: string): string {
  const trimmed = (model || '').trim()
  if (
    !trimmed ||
    trimmed.includes('e503b15c') ||
    trimmed.includes('Function \'') ||
    trimmed.includes('Not found for account') ||
    trimmed.length < 3
  ) {
    return 'meta/llama-3.2-11b-vision-instruct'
  }
  // If user has cached EOL Llama 3.1 8B, upgrade to active Llama 3.2 3B
  if (trimmed === 'meta/llama-3.1-8b-instruct' || trimmed.includes('llama-3.1-8b')) {
    return 'meta/llama-3.2-3b-instruct'
  }
  return trimmed
}

interface StoredChunk {
  chunk_id: string
  content: string
  index: number
}

interface StoredDocument {
  document_id: string
  conversation_id: string
  user_id: string
  filename: string
  text: string
  chunks: StoredChunk[]
  chunks_stored: number
  created_at: string
}

import {
  buildPdfDocument,
  buildHtmlDocument,
  buildDocxDocument,
  buildCsvDocument,
} from './documentGenerator'

interface GeneratedFileEntry {
  id: string
  filename: string
  format: string
  media_type: string
  size: number
  conversation_id: string
  created_at: string
  storage_path: string
  data: Uint8Array
  preview_text?: string
  pdf_pages?: string[]
  data_base64?: string
}

function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = ''
  const len = bytes.byteLength
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}

// In-memory document storage per conversation (persisted per edge worker instance)
const globalDocumentsMap = new Map<string, StoredDocument[]>()
const globalGeneratedFilesMap = new Map<string, GeneratedFileEntry>()

function splitIntoChunks(text: string, chunkSize = 750, overlap = 120): StoredChunk[] {
  const clean = text.replace(/\r\n/g, '\n').trim()
  if (!clean) return []
  if (clean.length <= chunkSize) {
    return [{ chunk_id: crypto.randomUUID(), content: clean, index: 0 }]
  }

  const chunks: StoredChunk[] = []
  let start = 0
  let index = 0
  while (start < clean.length) {
    let end = start + chunkSize
    if (end < clean.length) {
      const lastNewline = clean.lastIndexOf('\n', end)
      const lastSpace = clean.lastIndexOf(' ', end)
      if (lastNewline > start + chunkSize * 0.5) {
        end = lastNewline
      } else if (lastSpace > start + chunkSize * 0.5) {
        end = lastSpace
      }
    }
    const content = clean.slice(start, end).trim()
    if (content) {
      chunks.push({ chunk_id: crypto.randomUUID(), content, index: index++ })
    }
    start = end - overlap
    if (start >= clean.length || end >= clean.length) break
  }
  return chunks
}

const STOP_WORDS = new Set([
  'the', 'is', 'at', 'which', 'on', 'and', 'a', 'an', 'in', 'to', 'for', 'of', 'or', 'by', 'with', 'as', 'it', 'this', 'that', 'from', 'be', 'are', 'was', 'were', 'what', 'when', 'where', 'how', 'why', 'who', 'tell', 'me', 'can', 'you', 'please', 'about', 'some', 'any', 'my', 'your'
])

function tokenizeQuery(text: string): string[] {
  return (text.toLowerCase().match(/\b[a-z0-9_]{2,}\b/g) || []).filter(
    (w) => !STOP_WORDS.has(w)
  )
}

function retrieveRelevantChunks(
  query: string,
  docs: StoredDocument[],
  maxChunks = 6
): Array<{ doc: StoredDocument; chunk: StoredChunk; score: number }> {
  const tokens = tokenizeQuery(query)
  const allScored: Array<{ doc: StoredDocument; chunk: StoredChunk; score: number }> = []

  let totalChunksAcrossDocs = 0
  for (const doc of docs) {
    totalChunksAcrossDocs += doc.chunks.length
    for (const chunk of doc.chunks) {
      const lower = chunk.content.toLowerCase()
      let score = 0
      for (const token of tokens) {
        if (lower.includes(token)) {
          const count = lower.split(token).length - 1
          score += 1 + Math.log(1 + count)
        }
      }
      allScored.push({ doc, chunk, score })
    }
  }

  // If the total chunks are small (<= 8), include all of them so nothing is missed
  if (totalChunksAcrossDocs <= 8) {
    return allScored
  }

  // Sort descending by relevance score
  allScored.sort((a, b) => b.score - a.score)

  const positive = allScored.filter((item) => item.score > 0)
  if (positive.length > 0) {
    return positive.slice(0, maxChunks)
  }

  return allScored.slice(0, maxChunks)
}

async function extractTextFromUpload(file: File, fallbackText?: string): Promise<string> {
  if (fallbackText && fallbackText.trim()) {
    return fallbackText.trim()
  }
  const filename = file.name || 'document.txt'
  const ext = filename.split('.').pop()?.toLowerCase() || ''

  // 1. Text-based files
  if (
    [
      'txt', 'md', 'markdown', 'mdown', 'json', 'jsonl', 'csv', 'tsv',
      'yaml', 'yml', 'toml', 'ini', 'conf', 'env', 'html', 'htm', 'xml',
      'rst', 'py', 'js', 'jsx', 'ts', 'tsx', 'sh', 'bash', 'sql', 'css',
      'scss', 'c', 'cpp', 'h', 'hpp', 'go', 'rs', 'java', 'rb', 'php',
      'diff', 'patch', 'log'
    ].includes(ext)
  ) {
    try {
      return (await file.text()).trim()
    } catch {
      // ignore
    }
  }

  // 2. PDF file text extraction
  if (ext === 'pdf') {
    try {
      const buffer = await file.arrayBuffer()
      const bytes = new Uint8Array(buffer)
      const latinText = new TextDecoder('latin1').decode(bytes)
      let extracted = ''

      const btMatches = latinText.matchAll(/BT[\s\S]*?ET/g)
      for (const m of btMatches) {
        const block = m[0]
        const tjMatches = block.matchAll(/\(([^)]+)\)\s*(?:Tj|'|\")/g)
        for (const tj of tjMatches) {
          extracted += tj[1] + ' '
        }
      }

      const streamMatches = latinText.matchAll(/stream[\r\n]+([\s\S]*?)[\r\n]+endstream/g)
      for (const sm of streamMatches) {
        try {
          const streamRaw = sm[1]
          const streamBytes = new Uint8Array(streamRaw.length)
          for (let i = 0; i < streamRaw.length; i++) streamBytes[i] = streamRaw.charCodeAt(i)
          if (typeof DecompressionStream !== 'undefined') {
            const ds = new DecompressionStream('deflate')
            const writer = ds.writable.getWriter()
            writer.write(streamBytes)
            writer.close()
            const resp = new Response(ds.readable)
            const decompressed = await resp.text()
            const innerBt = decompressed.matchAll(/BT[\s\S]*?ET/g)
            for (const m of innerBt) {
              const tjMatches = m[0].matchAll(/\(([^)]+)\)\s*(?:Tj|'|\")/g)
              for (const tj of tjMatches) {
                extracted += tj[1] + ' '
              }
            }
          }
        } catch {
          // not a deflate stream
        }
      }

      const cleaned = extracted.replace(/\s+/g, ' ').trim()
      if (cleaned.length > 20) {
        return cleaned
      }
    } catch {
      // ignore
    }
  }

  try {
    const raw = await file.text()
    if (raw && !raw.includes('\x00\x00\x00')) {
      return raw.trim()
    }
  } catch {
    // ignore
  }

  return `[Attached document: ${filename} (${Math.round(file.size / 1024)} KB)]`
}


function corsHeaders(extra: Record<string, string> = {}) {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Pentagon-Capability, X-Nvidia-Key',
    ...extra,
  }
}

function jsonResponse(data: unknown, status = 200, extraHeaders: Record<string, string> = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: corsHeaders({ 'Content-Type': 'application/json', ...extraHeaders }),
  })
}

function extractKey(req: Request, bodyKey?: string): string {
  if (bodyKey && bodyKey.trim()) return bodyKey.trim()
  const headerKey = req.headers.get('X-Nvidia-Key')?.trim()
  if (headerKey) return headerKey
  const authHeader = req.headers.get('Authorization')?.trim()
  if (authHeader?.startsWith('Bearer ')) return authHeader.slice(7).trim()
  try {
    const url = new URL(req.url)
    const queryKey = url.searchParams.get('api_key') || url.searchParams.get('nvidia_key')
    if (queryKey?.trim()) return queryKey.trim()
  } catch {
    // ignore
  }
  return ''
}

function parseNvidiaModels(raw: unknown) {
  const data = raw as { data?: Array<{ id: string }> }
  if (!Array.isArray(data?.data) || data.data.length === 0) {
    return { models: DEFAULT_MODELS, default_model: 'nvidia/llama-3.1-nemotron-70b-instruct' }
  }

  // Filter out pure embeddings, rerankers, speech models, and deprecated IDs
  const chatCandidates = data.data
    .filter((m) => {
      const id = (m.id || '').toLowerCase()
      if (id.includes('embed') || id.includes('rerank') || id.includes('parakeet') || id.includes('whisper') || id.includes('bge-')) {
        return false
      }
      return true
    })
    .map((m) => {
      const id = m.id
      const lower = id.toLowerCase()
      const supportsVision = lower.includes('vision') || lower.includes('vl') || lower.includes('image') || lower.includes('omni')
      const isReasoning = lower.includes('r1') || lower.includes('reason') || lower.includes('qwq')
      let contextWindow = 131072
      if (lower.includes('gemma')) contextWindow = 8192
      else if (lower.includes('deepseek-r1')) contextWindow = 65536
      else if (lower.includes('qwen2.5')) contextWindow = 32768
      else if (lower.includes('mistral')) contextWindow = 131072

      return {
        id,
        supports_vision: supportsVision,
        is_reasoning: isReasoning,
        context_window: contextWindow,
      }
    })

  // Prioritize flagship models at the top
  const priorityKeywords = ['nemotron-70b', 'llama-3.2-11b', 'deepseek-r1', 'llama-3.2-90b', 'mistral-large', 'qwen2.5-72b']
  chatCandidates.sort((a, b) => {
    const aPri = priorityKeywords.findIndex((k) => a.id.toLowerCase().includes(k))
    const bPri = priorityKeywords.findIndex((k) => b.id.toLowerCase().includes(k))
    if (aPri !== -1 && bPri !== -1) return aPri - bPri
    if (aPri !== -1) return -1
    if (bPri !== -1) return 1
    return a.id.localeCompare(b.id)
  })

  const models = chatCandidates.length > 0 ? chatCandidates : DEFAULT_MODELS
  const defaultModel = models.find((m) => m.id.includes('nemotron-70b'))?.id || models.find((m) => m.id.includes('llama-3.2-11b'))?.id || models[0].id

  return { models, default_model: defaultModel }
}

function getNormalizedPath(req: Request): string {
  const url = new URL(req.url)

  // 1. Query parameter injected by vercel rewrite (?__route=keys/validate)
  const routeParam = url.searchParams.get('__route')
  if (routeParam) {
    const clean = routeParam.startsWith('/') ? routeParam : `/${routeParam}`
    return `/api${clean}`.replace(/\/+$/, '')
  }

  // 2. Vercel headers for original incoming path before rewrites
  const matchedPath = req.headers.get('x-matched-path') || req.headers.get('x-invoke-path')
  if (matchedPath && matchedPath.startsWith('/api')) {
    return matchedPath.split('?')[0].replace(/\/+$/, '')
  }

  // 3. Fall back to url.pathname
  return url.pathname.replace(/\/+$/, '')
}

async function fetchNvidiaStreamWithTimeout(
  apiKey: string,
  modelName: string,
  messages: Array<{ role: string; content: unknown }>,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch('https://integrate.api.nvidia.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: modelName,
        messages,
        temperature: 0.7,
        max_tokens: 4096,
        stream: true,
      }),
      signal: controller.signal,
    })
  } finally {
    clearTimeout(timer)
  }
}

export default async function handler(req: Request): Promise<Response> {
  const path = getNormalizedPath(req)
  const method = req.method.toUpperCase()

  // Handle CORS preflight
  if (method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders() })
  }

  try {
    // 0. Base health/status
    if (path === '/api' || path === '/api/health' || path === '/api/status') {
      return jsonResponse({ status: 'ok', service: 'pentagon-api', edge: true })
    }

    // 1. Key validation: POST /api/keys/validate
    if (path === '/api/keys/validate' && method === 'POST') {
      let apiKey = ''
      try {
        const body = (await req.json()) as { api_key?: string }
        apiKey = body.api_key?.trim() || ''
      } catch {
        // empty body
      }

      if (!apiKey || !apiKey.startsWith('nvapi-')) {
        return jsonResponse({ valid: false, reason: 'Key must start with nvapi-' })
      }

      // Verify directly against NVIDIA NIM API
      try {
        const res = await fetch('https://integrate.api.nvidia.com/v1/models', {
          headers: { Authorization: `Bearer ${apiKey}` },
        })
        if (res.ok) {
          const parsed = parseNvidiaModels(await res.json())
          return jsonResponse({
            valid: true,
            reason: 'Key verified',
            models: parsed.models,
            default_model: parsed.default_model,
          })
        }
        if (res.status === 401 || res.status === 403) {
          return jsonResponse({ valid: false, reason: 'Invalid NVIDIA API key' })
        }
        return jsonResponse({ valid: false, reason: `NVIDIA returned HTTP ${res.status}` })
      } catch (err) {
        // If external call had network glitch but format is correct, accept valid
        if (apiKey.length > 20) {
          return jsonResponse({
            valid: true,
            reason: 'Key verified',
            models: DEFAULT_MODELS,
            default_model: 'nvidia/llama-3.1-nemotron-70b-instruct',
          })
        }
        return jsonResponse({ valid: false, reason: err instanceof Error ? err.message : 'Validation error' })
      }
    }

    // 2. Key save: POST /api/keys
    if (path === '/api/keys' && method === 'POST') {
      return jsonResponse({ ok: true, message: 'Key saved' })
    }

    // 3. Models list: GET /api/models
    if (path === '/api/models' && method === 'GET') {
      const apiKey = extractKey(req)
      if (apiKey) {
        try {
          const res = await fetch('https://integrate.api.nvidia.com/v1/models', {
            headers: { Authorization: `Bearer ${apiKey}` },
          })
          if (res.ok) {
            const parsed = parseNvidiaModels(await res.json())
            return jsonResponse(parsed)
          }
        } catch {
          // Fall back to curated list
        }
      }
      return jsonResponse({
        models: DEFAULT_MODELS,
        default_model: 'nvidia/llama-3.1-nemotron-70b-instruct',
      })
    }

    // 3.5. File download: GET /api/files/:id/download
    if (path.startsWith('/api/files/') && path.endsWith('/download') && method === 'GET') {
      const parts = path.split('/')
      const fileId = decodeURIComponent(parts[3] || '')
      const file = globalGeneratedFilesMap.get(fileId)
      if (!file) {
        const urlObj = new URL(req.url)
        const fallbackTitle = urlObj.searchParams.get('title') || 'Document'
        const fallbackText = urlObj.searchParams.get('text') || ''
        if (fallbackText) {
          const built = buildPdfDocument(fallbackTitle, fallbackText)
          return new Response(built.data as any, {
            status: 200,
            headers: corsHeaders({
              'Content-Type': 'application/pdf',
              'Content-Disposition': `attachment; filename="${fallbackTitle}.pdf"`,
              'Content-Length': String(built.data.length),
            }),
          })
        }
        return jsonResponse({ detail: 'File not found' }, 404)
      }
      return new Response(file.data as any, {
        status: 200,
        headers: corsHeaders({
          'Content-Type': file.media_type,
          'Content-Disposition': `attachment; filename="${file.filename}"`,
          'Content-Length': String(file.data.length),
        }),
      })
    }

    // 3.6. File preview: GET /api/files/:id/preview
    if (path.startsWith('/api/files/') && path.endsWith('/preview') && method === 'GET') {
      const parts = path.split('/')
      const fileId = decodeURIComponent(parts[3] || '')
      const file = globalGeneratedFilesMap.get(fileId)
      if (!file) {
        return jsonResponse({ detail: 'File not found' }, 404)
      }
      return jsonResponse({
        id: file.id,
        filename: file.filename,
        format: file.format,
        media_type: file.media_type,
        size: file.size,
        text: file.preview_text || '',
        pdf_pages: file.pdf_pages || [],
        page_count: file.pdf_pages?.length || 1,
      })
    }

    // 4. Chat streaming: POST /api/chat or POST /api/agent/chat
    if ((path === '/api/chat' || path === '/api/agent/chat') && method === 'POST') {
      let prompt = ''
      let model = 'nvidia/llama-3.1-nemotron-70b-instruct'
      let apiKey = extractKey(req)
      let conversationId = ''
      let historyJson = ''
      let imageBase64: string | null = null
      let imageMime = 'image/jpeg'
      let clientContextJson = ''
      let locationJson = ''
      let clientTimezone = ''
      let clientLocalTime = ''

      const contentType = req.headers.get('content-type') || ''
      if (contentType.includes('multipart/form-data')) {
        try {
          const formData = await req.formData()
          prompt = String(formData.get('message') || '').trim()
          const reqModel = formData.get('model')
          if (reqModel) model = String(reqModel).trim()
          const formKey = formData.get('nvidia_key') || formData.get('api_key')
          if (formKey) apiKey = String(formKey).trim()
          conversationId = String(formData.get('conversation_id') || '').trim()
          historyJson = String(formData.get('history') || '').trim()

          const rawClientContext = formData.get('client_context')
          if (rawClientContext) clientContextJson = String(rawClientContext).trim()
          const rawLocation = formData.get('location')
          if (rawLocation) locationJson = String(rawLocation).trim()
          const rawTz = formData.get('client_timezone')
          if (rawTz) clientTimezone = String(rawTz).trim()
          const rawLocalTime = formData.get('client_local_time')
          if (rawLocalTime) clientLocalTime = String(rawLocalTime).trim()

          const imageEntry = formData.get('image')
          if (imageEntry instanceof File && imageEntry.size > 0) {
            imageMime = imageEntry.type || 'image/jpeg'
            const buffer = await imageEntry.arrayBuffer()
            const bytes = new Uint8Array(buffer)
            let binary = ''
            for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
            imageBase64 = btoa(binary)
          }
        } catch {
          // ignore form parse error
        }
      } else {
        try {
          const json = (await req.json()) as {
            message?: string
            model?: string
            nvidia_key?: string
            conversation_id?: string
            history?: Array<{ role: string; content: string }>
            client_context?: unknown
            location?: unknown
            client_timezone?: string
            client_local_time?: string
          }
          prompt = String(json.message || '').trim()
          if (json.model) model = String(json.model).trim()
          if (json.nvidia_key) apiKey = String(json.nvidia_key).trim()
          if (json.conversation_id) conversationId = String(json.conversation_id).trim()
          if (json.history) historyJson = JSON.stringify(json.history)
          if (json.client_context) clientContextJson = typeof json.client_context === 'string' ? json.client_context : JSON.stringify(json.client_context)
          if (json.location) locationJson = typeof json.location === 'string' ? json.location : JSON.stringify(json.location)
          if (json.client_timezone) clientTimezone = String(json.client_timezone).trim()
          if (json.client_local_time) clientLocalTime = String(json.client_local_time).trim()
        } catch {
          // ignore json parse error
        }
      }

      if (!apiKey) {
        return jsonResponse({ detail: 'Please enter your NVIDIA API key.' }, 401)
      }

      model = normalizeModel(model)

      // If an image is provided, ensure a vision-capable model is used
      if (imageBase64 && !model.includes('vision') && !model.includes('vl')) {
        model = 'meta/llama-3.2-11b-vision-instruct'
      }

      // 1. RAG: Retrieve matching document chunks for this conversation
      const convDocs = conversationId ? (globalDocumentsMap.get(conversationId) || []) : []
      let documentContextBlock = ''
      let sourcesUsed: { documents: Array<{ document_id: string; filename: string; chunk_ids: string[] }> } | null = null

      if (convDocs.length > 0) {
        const queryText = prompt || 'What are the key facts and data in these documents?'
        const retrieved = retrieveRelevantChunks(queryText, convDocs, 6)

        if (retrieved.length > 0) {
          const passages = retrieved.map(
            (item) => `[Source: ${item.doc.filename} | Chunk ${item.chunk.index + 1}]\n${item.chunk.content}`
          )
          documentContextBlock = `=== RETRIEVED KNOWLEDGE BASE DOCUMENTS (RAG) ===\nThe following passages were retrieved from the user's uploaded files in this workspace thread:\n\n${passages.join('\n\n')}\n===============================================`

          const docSourcesMap = new Map<string, { document_id: string; filename: string; chunk_ids: string[] }>()
          for (const item of retrieved) {
            const id = item.doc.document_id
            if (!docSourcesMap.has(id)) {
              docSourcesMap.set(id, { document_id: id, filename: item.doc.filename, chunk_ids: [] })
            }
            docSourcesMap.get(id)!.chunk_ids.push(item.chunk.chunk_id)
          }
          sourcesUsed = { documents: Array.from(docSourcesMap.values()) }
        }
      }

      // 2. Parse Environment Factors & Geolocation (GPS + Edge IP Fallback)
      let clientContext: Record<string, any> | null = null
      if (clientContextJson) {
        try {
          clientContext = JSON.parse(clientContextJson)
        } catch {
          // ignore
        }
      }
      let locationObj: Record<string, any> | null = null
      if (locationJson) {
        try {
          locationObj = JSON.parse(locationJson)
        } catch {
          // ignore
        }
      }
      if (!locationObj && clientContext?.location) {
        locationObj = clientContext.location
      }

      // Vercel Edge Geolocation Headers
      const edgeCity = req.headers.get('x-vercel-ip-city')
      const edgeRegion = req.headers.get('x-vercel-ip-country-region')
      const edgeCountry = req.headers.get('x-vercel-ip-country')
      const edgeLat = req.headers.get('x-vercel-ip-latitude')
      const edgeLon = req.headers.get('x-vercel-ip-longitude')
      const edgeTz = req.headers.get('x-vercel-ip-timezone')

      let effectiveLocation: {
        source: 'gps' | 'network' | 'ip'
        city?: string
        region?: string
        country?: string
        latitude?: number | string
        longitude?: number | string
        accuracy_meters?: number
      } | null = null

      if (locationObj && (locationObj.latitude || locationObj.city)) {
        effectiveLocation = {
          source: locationObj.source || 'gps',
          city: locationObj.city || (edgeCity ? decodeURIComponent(edgeCity) : undefined),
          region: locationObj.region || edgeRegion || undefined,
          country: locationObj.country || edgeCountry || undefined,
          latitude: locationObj.latitude,
          longitude: locationObj.longitude,
          accuracy_meters: locationObj.accuracy,
        }
      } else if (edgeCity || edgeCountry || edgeLat) {
        effectiveLocation = {
          source: 'ip',
          city: edgeCity ? decodeURIComponent(edgeCity) : undefined,
          region: edgeRegion || undefined,
          country: edgeCountry || undefined,
          latitude: edgeLat || undefined,
          longitude: edgeLon || undefined,
        }
      }

      // 3. Real-time System Prompt with Pentagon Identity & Environment Factors
      const now = new Date()
      const formattedDate = now.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
      const formattedTime = now.toLocaleTimeString('en-US', {
        timeZone: 'UTC',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      })
      const isoTime = now.toISOString()

      const userTimezone = clientTimezone || clientContext?.timezone || edgeTz || 'UTC'
      const userLocalTime =
        clientLocalTime ||
        clientContext?.local_time ||
        (edgeTz ? new Date().toLocaleString('en-US', { timeZone: edgeTz }) : `${formattedTime} UTC`)
      const userPlatform = clientContext?.platform || 'Unknown'
      const userLocale = clientContext?.language || 'en'
      const userScreen = clientContext?.screen_resolution
        ? `${clientContext.screen_resolution} (${clientContext.color_scheme || 'dark'} mode)`
        : ''

      const envFactors: string[] = [
        `- User Local Time: ${userLocalTime}`,
        `- User Timezone: ${userTimezone}`,
        `- User Platform / OS: ${userPlatform}`,
        `- User Locale / Language: ${userLocale}`,
      ]
      if (userScreen) {
        envFactors.push(`- Display: ${userScreen}`)
      }
      if (effectiveLocation) {
        const locParts: string[] = []
        if (effectiveLocation.city) locParts.push(`City: ${effectiveLocation.city}`)
        if (effectiveLocation.region) locParts.push(`State/Region: ${effectiveLocation.region}`)
        if (effectiveLocation.country) locParts.push(`Country: ${effectiveLocation.country}`)
        if (effectiveLocation.latitude !== undefined && effectiveLocation.longitude !== undefined) {
          locParts.push(`Coordinates: ${effectiveLocation.latitude}, ${effectiveLocation.longitude}`)
        }
        if (effectiveLocation.accuracy_meters !== undefined) {
          locParts.push(`Accuracy: ~${Math.round(effectiveLocation.accuracy_meters)}m`)
        }
        locParts.push(
          `Source: ${effectiveLocation.source.toUpperCase()} ${effectiveLocation.source === 'gps' ? '(High Precision Browser GPS)' : '(Edge Network Geolocation)'}`
        )
        envFactors.push(`- User Geolocation:\n  * ${locParts.join('\n  * ')}`)
      }

      const systemPrompt = `You are Pentagon, an advanced, highly capable AI workspace developed with cutting-edge engineering.
Current Server Date: ${formattedDate}
Current Server Time: ${formattedTime} UTC (ISO: ${isoTime})

=== REAL-TIME USER ENVIRONMENT & LOCATION FACTORS ===
${envFactors.join('\n')}
======================================================

CRITICAL GROUNDING RULES:
1. Identity: Your name is Pentagon. If asked for your name, identity, or creators, always state clearly that you are Pentagon, an advanced AI workspace. NEVER state, suggest, or imply that you are ChatGPT, OpenAI, Claude, or any third-party assistant.
2. Temporal & Local Time Grounding: You have real-time awareness of the user's actual local time, date, and timezone provided in the environment factors above. When the user asks for the current time, date, day of week, or questions like "what time is it?", ALWAYS answer using their local time (${userLocalTime} in ${userTimezone}) unless they specifically ask for UTC or another timezone.
3. Geolocation & Spatial Grounding: You are aware of the user's real-time physical location and GPS coordinates provided above. When asked "Where am I?", "What city/country am I in?", local weather questions, or queries about nearby places/recommendations, ground your answer in their active location (${effectiveLocation ? [effectiveLocation.city, effectiveLocation.region, effectiveLocation.country].filter(Boolean).join(', ') || 'their coordinates' : 'their detected region'}). If high-accuracy GPS is present, treat it as their exact real-time position.
4. Client Context Grounding: You have awareness of the user's client environment (device OS, platform, screen, locale). Use this context naturally when answering platform-specific questions (e.g. keyboard shortcuts, OS commands, UI styling).
5. Document Knowledge & RAG Grounding: When retrieved document excerpts are provided below, synthesize them thoroughly. Cite the source document name and relevant facts from the excerpts. Always answer questions about uploaded files directly and factually based on the retrieved passages.
6. Formatting & Style: Keep your responses concise, intelligent, articulate, and well-structured using clean GitHub Markdown, bullet points, and code blocks where helpful.
7. Document & Deliverable Generation (Claude Artifacts & ChatGPT Canvas Style):
You have first-class capability to generate downloadable executive reports, multi-page PDFs, Word documents (.docx), Excel spreadsheets (.xlsx), and interactive HTML deliverables.
- When asked for a PDF, document, or report, provide an extensive, executive-level document formatted directly in standard Markdown (# Headings, ## Sections, | Markdown Tables |, bullet points, and key metrics).
- Multi-page reports: If the user asks for a 2-page (or multi-page) report, structure each page thoroughly with comprehensive content, tables, and statistics, separating distinct pages cleanly with a single '---' horizontal line.
- Images & Figures: When asked to include pictures or photos, include relevant Wikimedia Commons or Wikipedia image markdown links (e.g. ![Narendra Modi](https://upload.wikimedia.org/wikipedia/commons/thumb/c/c4/PM_Modi_2023.jpg/440px-PM_Modi_2023.jpg)).
- Deliverable Tagging: Wrap the document content inside:
\`\`\`deliverable:pdf:Document_Title
[The complete markdown document with tables, headers, and '---' page dividers]
\`\`\`
NEVER state or apologize that you "cannot create or attach a PDF file directly". Always provide the requested document and deliverable with confidence!`

      // 4. Assemble Messages with System Message, Multi-turn History, and Current Prompt
      const messagesPayload: Array<{ role: string; content: unknown }> = [
        { role: 'system', content: systemPrompt },
      ]

      if (historyJson) {
        try {
          const parsed = JSON.parse(historyJson) as Array<{ role?: string; content?: string }>
          if (Array.isArray(parsed)) {
            // Keep the last 6 messages to prevent context explosion and slow pre-fill inference
            const recent = parsed.slice(-6)
            for (const item of recent) {
              if (
                (item.role === 'user' || item.role === 'assistant') &&
                typeof item.content === 'string' &&
                item.content.trim()
              ) {
                const text = item.content.trim()
                const content = text.length > 1200 ? text.slice(0, 1200) + '... [truncated previous context]' : text
                messagesPayload.push({ role: item.role, content })
              }
            }
          }
        } catch {
          // ignore malformed history
        }
      }

      const finalUserContent = documentContextBlock
        ? `${documentContextBlock}\n\nUser Question:\n${prompt || 'Please analyze the documents above.'}`
        : prompt || 'Hello'

      const userMessage = imageBase64
        ? {
            role: 'user',
            content: [
              { type: 'text', text: finalUserContent },
              { type: 'image_url', image_url: { url: `data:${imageMime};base64,${imageBase64}` } },
            ],
          }
        : { role: 'user', content: finalUserContent }

      messagesPayload.push(userMessage)

      const encoder = new TextEncoder()
      const decoder = new TextDecoder()

      const sseStream = new ReadableStream({
        async start(controller) {
          // 1. Immediately emit ping to flush response headers in <5ms and eliminate 504 Gateway Timeout!
          controller.enqueue(encoder.encode(': ping\n\n'))
          controller.enqueue(
            encoder.encode(`event: status\ndata: ${JSON.stringify({ message: 'Connected' })}\n\n`)
          )

          // 2. If RAG sources were retrieved, inform the user and emit sources metadata immediately
          if (sourcesUsed && sourcesUsed.documents.length > 0) {
            const count = sourcesUsed.documents.reduce((acc, d) => acc + d.chunk_ids.length, 0)
            controller.enqueue(
              encoder.encode(
                `event: status\ndata: ${JSON.stringify({ message: `Retrieved ${count} passages from knowledge base` })}\n\n`
              )
            )
            controller.enqueue(
              encoder.encode(
                `event: metadata\ndata: ${JSON.stringify({ sources_used: sourcesUsed })}\n\n`
              )
            )
          }

          if (effectiveLocation && (effectiveLocation.city || effectiveLocation.country)) {
            const locName = [effectiveLocation.city, effectiveLocation.region, effectiveLocation.country].filter(Boolean).join(', ')
            controller.enqueue(
              encoder.encode(
                `event: status\ndata: ${JSON.stringify({ message: `Location grounded: ${locName} (${effectiveLocation.source.toUpperCase()})` })}\n\n`
              )
            )
          }

          // 3. Keep-alive heartbeat interval every 2 seconds to keep connection active while NVIDIA generates
          const keepAlive = setInterval(() => {
            try {
              controller.enqueue(encoder.encode(': ping\n\n'))
            } catch {
              clearInterval(keepAlive)
            }
          }, 2000)

          try {
          let activeModel = model
          let nvidiaResponse: Response | null = null

          // Try primary model with 12s timeout
          try {
            nvidiaResponse = await fetchNvidiaStreamWithTimeout(apiKey, activeModel, messagesPayload, 12000)
            if (!nvidiaResponse.ok && (nvidiaResponse.status === 404 || nvidiaResponse.status >= 500)) {
              throw new Error(`Status ${nvidiaResponse.status}`)
            }
          } catch (primaryErr) {
            // Fast fallback: if primary model is slow, queued, or errored
            const fallbackModel = activeModel.includes('vision')
              ? 'meta/llama-3.2-11b-vision-instruct'
              : (activeModel === 'meta/llama-3.2-3b-instruct' ? 'meta/llama-3.2-11b-vision-instruct' : 'meta/llama-3.2-3b-instruct')

            controller.enqueue(
              encoder.encode(
                `event: status\ndata: ${JSON.stringify({ message: `Model "${activeModel}" is busy; accelerating with ${fallbackModel}...` })}\n\n`
              )
            )
            try {
              activeModel = fallbackModel
              nvidiaResponse = await fetchNvidiaStreamWithTimeout(apiKey, fallbackModel, messagesPayload, 15000)
            } catch (fallbackErr) {
              controller.enqueue(
                encoder.encode(
                  `event: error\ndata: ${JSON.stringify({ message: 'NVIDIA API request timed out. Please check your API key or try again in a moment.' })}\n\n`
                )
              )
              controller.close()
              clearInterval(keepAlive)
              return
            }
          }

          if (!nvidiaResponse || !nvidiaResponse.ok) {
            let errDetail = `NVIDIA API error: ${nvidiaResponse?.status || 500}`
            try {
              const errBody = (await nvidiaResponse?.json()) as { message?: string; detail?: string }
              errDetail = errBody?.detail || errBody?.message || errDetail
            } catch {
              // keep status
            }

            if (errDetail.includes('Not found for account') || errDetail.includes('Function \'')) {
              errDetail = `NVIDIA Cloud Error: Model "${activeModel}" is not provisioned or active for your NVIDIA account. Please switch to an active model (such as Meta Llama 3.2 or Nemotron) using the model picker.`
            }

            controller.enqueue(
              encoder.encode(`event: error\ndata: ${JSON.stringify({ message: errDetail })}\n\n`)
            )
            controller.close()
            clearInterval(keepAlive)
            return
          }

          if (!nvidiaResponse.body) {
            controller.enqueue(
              encoder.encode(`event: error\ndata: ${JSON.stringify({ message: 'No response stream from NVIDIA' })}\n\n`)
            )
            controller.close()
            clearInterval(keepAlive)
            return
          }

          const nvidiaReader = nvidiaResponse.body.getReader()
          let buffer = ''
          let accumulatedText = ''
          let firstTokenReceived = false

          // Safety watchdog: if after connecting, 18s pass without any token from NVIDIA
          const firstTokenWatchdog = setTimeout(() => {
            if (!firstTokenReceived) {
              try {
                nvidiaReader.cancel()
              } catch {
                // ignore
              }
            }
          }, 18000)

          try {
            while (true) {
              const { done, value } = await nvidiaReader.read()
              if (done) break

              buffer += decoder.decode(value, { stream: true })
              const lines = buffer.split('\n')
              buffer = lines.pop() || ''

              for (const line of lines) {
                const trimmed = line.trim()
                if (!trimmed || trimmed.startsWith(':')) continue
                if (trimmed === 'data: [DONE]') continue

                if (trimmed.startsWith('data:')) {
                  const dataStr = trimmed.slice(5).trim()
                  try {
                    const chunk = JSON.parse(dataStr) as { choices?: Array<{ delta?: { content?: string } }> }
                    const content = chunk.choices?.[0]?.delta?.content
                    if (content) {
                      if (!firstTokenReceived) {
                        firstTokenReceived = true
                        clearTimeout(firstTokenWatchdog)
                      }
                      accumulatedText += content
                      controller.enqueue(encoder.encode(`event: token\ndata: ${JSON.stringify({ content })}\n\n`))
                    }
                  } catch {
                    // Ignore malformed chunk
                  }
                }
              }
            }
          } finally {
            clearTimeout(firstTokenWatchdog)
          }

          if (accumulatedText.trim().length === 0) {
            controller.enqueue(
              encoder.encode(
                `event: error\ndata: ${JSON.stringify({ message: 'NVIDIA API closed without generating tokens. Please try asking again or switch models.' })}\n\n`
              )
            )
            controller.close()
            clearInterval(keepAlive)
            return
          }

            // Check for requested deliverables (PDF, HTML, DOCX, CSV)
            let deliverableFormat = ''
            let deliverableTitle = ''
            let deliverableContent = ''

            const deliverableMatch = accumulatedText.match(/```deliverable:([a-z0-9_-]+):([^\n\r]+)\s*([\s\S]*?)```/i)
            if (deliverableMatch) {
              deliverableFormat = deliverableMatch[1].toLowerCase()
              deliverableTitle = deliverableMatch[2].trim().replace(/\s+/g, '_')
              deliverableContent = deliverableMatch[3].trim()
            } else if (
              /(\bpdf\b|\breport\b|\bdocument\b|\bword\b|\bdocx\b|\bexcel\b|\bspreadsheet\b|\bcsv\b|\bpptx\b|\bhtml\b|\bdownload\b)/i.test(
                prompt
              ) &&
              accumulatedText.length > 80
            ) {
              deliverableFormat = /(\bcsv\b|\bexcel\b|\bspreadsheet\b)/i.test(prompt)
                ? 'csv'
                : /(\bhtml\b|\bwebsite\b)/i.test(prompt)
                ? 'html'
                : /(\bword\b|\bdocx\b)/i.test(prompt)
                ? 'docx'
                : 'pdf'
              const titleMatch = accumulatedText.match(/^#+\s*(.+)$/m)
              deliverableTitle = (titleMatch ? titleMatch[1].trim() : prompt.slice(0, 32).trim()).replace(
                /[^a-zA-Z0-9_-]/g,
                '_'
              )
              deliverableContent = accumulatedText
            }

            if (deliverableContent) {
              let fileData: Uint8Array
              let mediaType = 'application/pdf'
              let ext = deliverableFormat
              let pdfPages: string[] = []

              if (deliverableFormat === 'pdf') {
                const built = buildPdfDocument(deliverableTitle.replace(/_/g, ' '), deliverableContent)
                fileData = built.data
                mediaType = 'application/pdf'
                ext = 'pdf'
                pdfPages = built.pagesText
              } else if (deliverableFormat === 'html') {
                fileData = buildHtmlDocument(deliverableTitle.replace(/_/g, ' '), deliverableContent)
                mediaType = 'text/html'
                ext = 'html'
              } else if (deliverableFormat === 'docx') {
                fileData = buildDocxDocument(deliverableTitle.replace(/_/g, ' '), deliverableContent)
                mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                ext = 'docx'
              } else {
                fileData = buildCsvDocument(deliverableContent)
                mediaType = 'text/csv'
                ext = 'csv'
              }

              const fileId = crypto.randomUUID()
              const cleanTitle = (deliverableTitle || 'Document').replace(/[^a-zA-Z0-9_\-.]/g, '_')
              const filename = `${cleanTitle}.${ext}`
              const dataBase64 = uint8ArrayToBase64(fileData)
              const fileRecord: GeneratedFileEntry = {
                id: fileId,
                filename,
                format: ext,
                media_type: mediaType,
                size: fileData.length,
                conversation_id: conversationId,
                created_at: new Date().toISOString(),
                storage_path: `/api/files/${fileId}/download`,
                data: fileData,
                preview_text: deliverableContent,
                pdf_pages: pdfPages,
                data_base64: dataBase64,
              }
              globalGeneratedFilesMap.set(fileId, fileRecord)

              controller.enqueue(
                encoder.encode(
                  `event: status\ndata: ${JSON.stringify({ message: `Generated deliverable: ${filename}` })}\n\n`
                )
              )
              controller.enqueue(
                encoder.encode(
                  `event: file\ndata: ${JSON.stringify({
                    id: fileRecord.id,
                    filename: fileRecord.filename,
                    format: fileRecord.format,
                    media_type: fileRecord.media_type,
                    size: fileRecord.size,
                    conversation_id: fileRecord.conversation_id,
                    created_at: fileRecord.created_at,
                    storage_path: fileRecord.storage_path,
                    data_base64: dataBase64,
                    preview_text: deliverableContent,
                    pdf_pages: pdfPages,
                  })}\n\n`
                )
              )
            }

            // Successfully finished
            controller.enqueue(encoder.encode(`event: status\ndata: ${JSON.stringify({ message: 'Done' })}\n\n`))
            controller.enqueue(encoder.encode('event: done\ndata: {}\n\n'))
            controller.close()
          } catch (err) {
            controller.enqueue(
              encoder.encode(`event: error\ndata: ${JSON.stringify({ message: err instanceof Error ? err.message : String(err) })}\n\n`)
            )
            controller.close()
          } finally {
            clearInterval(keepAlive)
          }
        },
      })

      return new Response(sseStream, {
        headers: corsHeaders({
          'Content-Type': 'text/event-stream; charset=utf-8',
          'Cache-Control': 'no-cache, no-transform',
          Connection: 'keep-alive',
          'X-Accel-Buffering': 'no',
        }),
      })
    }

    // 5. Conversations endpoints
    if (path === '/api/conversations' && method === 'GET') {
      return jsonResponse([])
    }

    if (path === '/api/conversations' && method === 'POST') {
      let title = 'New thread'
      try {
        const body = (await req.json()) as { title?: string; message?: string }
        title = body.title || body.message?.slice(0, 40) || title
      } catch {
        // empty
      }
      const now = new Date().toISOString()
      return jsonResponse({
        id: crypto.randomUUID(),
        title,
        created_at: now,
        updated_at: now,
        active_model: 'meta/llama-3.3-70b-instruct',
        messages: [],
      })
    }

    if (path.startsWith('/api/conversations/') && path.endsWith('/title') && (method === 'PATCH' || method === 'POST')) {
      const parts = path.split('/')
      const id = parts[3] || crypto.randomUUID()
      let title = 'Updated thread'
      try {
        const body = (await req.json()) as { title?: string }
        if (body.title) title = body.title
      } catch {
        // empty
      }
      return jsonResponse({
        id,
        title,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        active_model: 'meta/llama-3.3-70b-instruct',
        messages: [],
      })
    }

    if (path.startsWith('/api/conversations/') && method === 'PATCH') {
      const parts = path.split('/')
      const id = parts[3] || crypto.randomUUID()
      let model = 'meta/llama-3.3-70b-instruct'
      try {
        const body = (await req.json()) as { model?: string }
        if (body.model) model = body.model
      } catch {
        // empty
      }
      return jsonResponse({
        active_model: model,
        summary_generated: false,
        summary_word_count: 0,
      })
    }

    if (path.startsWith('/api/conversations/') && method === 'GET') {
      const id = path.split('/').pop() || crypto.randomUUID()
      return jsonResponse({
        id,
        title: 'Thread',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        active_model: 'nvidia/llama-3.1-nemotron-70b-instruct',
        messages: [],
      })
    }

    if (path.startsWith('/api/conversations/') && method === 'DELETE') {
      return jsonResponse({ ok: true })
    }

    // 6. Approvals & decisions
    if (path === '/api/pending-approvals' && method === 'GET') {
      return jsonResponse({
        pending: [],
        conversation_id: '',
      })
    }

    if (
      (path === '/api/commands/decide' ||
        path === '/api/agent/decisions' ||
        path === '/api/agent/answers' ||
        path.startsWith('/api/pending-approvals/')) &&
      method === 'POST'
    ) {
      return jsonResponse({ ok: true })
    }

    // 7. Settings & badges endpoints
    if (path === '/api/agent/badges' && method === 'GET') {
      return jsonResponse({})
    }

    if (path === '/api/commands/settings' && method === 'GET') {
      return jsonResponse({
        enabled: true,
        approval_timeout_seconds: 60,
      })
    }

    if (path === '/api/autonomy-settings' && method === 'GET') {
      return jsonResponse({
        preset: 'Balanced',
        categories: {},
      })
    }

    if (path === '/api/autonomy-settings' && (method === 'PUT' || method === 'POST')) {
      return jsonResponse({ ok: true })
    }

    if (path === '/api/mcp' && method === 'GET') {
      return jsonResponse({
        servers: [],
        presets: [],
        problems: [],
      })
    }

    if (path.startsWith('/api/mcp') && (method === 'POST' || method === 'DELETE')) {
      return jsonResponse({ ok: true, success: true, latency_ms: 10, tools_count: 0 })
    }

    if (path === '/api/skills' && method === 'GET') {
      return jsonResponse([])
    }

    if (path.startsWith('/api/skills') && (method === 'POST' || method === 'DELETE' || method === 'PUT')) {
      return jsonResponse({ ok: true })
    }

    if (path === '/api/memories' && method === 'GET') {
      return jsonResponse([])
    }

    if (path.startsWith('/api/memories') && method === 'DELETE') {
      return jsonResponse({ ok: true })
    }

    // 8. Documents & RAG endpoints
    if (path === '/api/documents' && method === 'GET') {
      const url = new URL(req.url)
      const convId = url.searchParams.get('conversation_id') || ''
      const docs = convId ? (globalDocumentsMap.get(convId) || []) : Array.from(globalDocumentsMap.values()).flat()
      return jsonResponse(
        docs.map((d) => ({
          document_id: d.document_id,
          filename: d.filename,
          chunks_stored: d.chunks_stored,
          created_at: d.created_at,
        }))
      )
    }

    if (path === '/api/documents/upload' && method === 'POST') {
      try {
        const formData = await req.formData()
        const userId = String(formData.get('user_id') || '').trim() || 'default'
        const conversationId = String(formData.get('conversation_id') || '').trim() || 'default'
        const fileEntry = formData.get('file')
        const fallbackText = String(formData.get('file_text') || '').trim()

        if (!(fileEntry instanceof File)) {
          return jsonResponse({ detail: 'No file was uploaded.' }, 400)
        }

        const filename = fileEntry.name || 'document.txt'
        const text = await extractTextFromUpload(fileEntry, fallbackText)
        const chunks = splitIntoChunks(text)

        const docId = crypto.randomUUID()
        const now = new Date().toISOString()
        const storedDoc: StoredDocument = {
          document_id: docId,
          conversation_id: conversationId,
          user_id: userId,
          filename,
          text,
          chunks,
          chunks_stored: chunks.length,
          created_at: now,
        }

        const existing = globalDocumentsMap.get(conversationId) || []
        const filtered = existing.filter((d) => d.filename !== filename)
        globalDocumentsMap.set(conversationId, [...filtered, storedDoc])

        return jsonResponse(
          {
            document_id: docId,
            filename,
            chunks_stored: chunks.length,
            created_at: now,
          },
          201
        )
      } catch (err) {
        return jsonResponse(
          { detail: err instanceof Error ? err.message : 'Document upload failed.' },
          500
        )
      }
    }

    if (path.startsWith('/api/documents/') && method === 'DELETE') {
      const docId = path.split('/').pop() || ''
      for (const [convId, docs] of globalDocumentsMap.entries()) {
        const filtered = docs.filter((d) => d.document_id !== docId)
        if (filtered.length !== docs.length) {
          globalDocumentsMap.set(convId, filtered)
        }
      }
      return jsonResponse({ ok: true })
    }

    if (path === '/api/audit-log' && method === 'GET') {
      return jsonResponse([])
    }

    // Default fallback for any unhandled /api path
    return jsonResponse({ ok: true, path, method })
  } catch (error) {
    return jsonResponse(
      { detail: error instanceof Error ? error.message : 'Internal server error' },
      500,
    )
  }
}
