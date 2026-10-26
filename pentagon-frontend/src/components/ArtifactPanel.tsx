import { useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  Code2,
  Copy,
  Download,
  ExternalLink,
  Eye,
  FileCode,
  Globe,
  Maximize2,
  Minimize2,
  Monitor,
  RotateCw,
  Server,
  Smartphone,
  Tablet,
  X,
} from 'lucide-react'
import type { ArtifactItem } from '../types'
import { startLocalhostServer } from '../api'

interface ArtifactPanelProps {
  artifact: ArtifactItem | null
  artifactsHistory?: ArtifactItem[]
  onSelectArtifact?: (artifact: ArtifactItem) => void
  onClose: () => void
}

type ViewportMode = 'desktop' | 'tablet' | 'mobile'

export function ArtifactPanel({
  artifact,
  artifactsHistory = [],
  onSelectArtifact,
  onClose,
}: ArtifactPanelProps) {
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview')
  const [viewport, setViewport] = useState<ViewportMode>('desktop')
  const [copied, setCopied] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [serverUrl, setServerUrl] = useState<string | null>(null)
  const [isHosting, setIsHosting] = useState(false)
  const [hostError, setHostError] = useState<string | null>(null)
  const iframeRef = useRef<HTMLIFrameElement>(null)

  // Track previous artifact ID and adjust state during render (React recommended pattern)
  const [prevArtifactId, setPrevArtifactId] = useState<string | undefined>(artifact?.id)
  if (artifact && artifact.id !== prevArtifactId) {
    setPrevArtifactId(artifact.id)
    setServerUrl(null)
    setHostError(null)
    setReloadKey((k) => k + 1)
    const lang = artifact.language.toLowerCase()
    const isWeb = ['html', 'htm', 'svg', 'react', 'jsx', 'tsx'].includes(lang)
    setViewMode(isWeb ? 'preview' : 'code')
  }

  const isPreviewable = useMemo(() => {
    if (!artifact) return false
    const lang = artifact.language.toLowerCase()
    return ['html', 'htm', 'svg', 'xml', 'react', 'jsx', 'tsx', 'markdown', 'md'].includes(lang)
  }, [artifact])

  // Generate safe HTML bundle for preview
  const previewHtml = useMemo(() => {
    if (!artifact) return ''
    const raw = artifact.content.trim()
    const lang = artifact.language.toLowerCase()

    if (lang === 'svg' || raw.startsWith('<svg')) {
      return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {
      margin: 0;
      padding: 24px;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      background: #0f1015;
    }
    svg {
      max-width: 100%;
      height: auto;
      filter: drop-shadow(0 10px 25px rgba(0,0,0,0.5));
    }
  </style>
</head>
<body>${raw}</body>
</html>`
    }

    if (lang === 'html' || lang === 'htm' || raw.includes('<!DOCTYPE') || raw.includes('<html')) {
      if (!raw.includes('tailwindcss')) {
        return raw.replace(
          '<head>',
          '<head><script src="https://cdn.tailwindcss.com"></script><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        )
      }
      return raw
    }

    // Default HTML wrapper with Tailwind CDN
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', sans-serif; margin: 0; padding: 0; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  ${raw}
</body>
</html>`
  }, [artifact])

  // Calculate code line count
  const lines = useMemo(() => (artifact ? artifact.content.split('\n') : []), [artifact])

  if (!artifact) return null

  const handleCopy = async () => {
    await navigator.clipboard.writeText(artifact.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const handleDownload = () => {
    const extMap: Record<string, string> = {
      html: 'html',
      javascript: 'js',
      typescript: 'ts',
      jsx: 'jsx',
      tsx: 'tsx',
      python: 'py',
      css: 'css',
      json: 'json',
      svg: 'svg',
      markdown: 'md',
    }
    const ext = extMap[artifact.language.toLowerCase()] || artifact.language.toLowerCase() || 'txt'
    const cleanName = artifact.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'artifact'
    const filename = `${cleanName}.${ext}`

    const blob = new Blob([artifact.content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleOpenTab = () => {
    const blob = new Blob([previewHtml], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
  }

  const handleRunLocalhost = async () => {
    setIsHosting(true)
    setHostError(null)
    try {
      const res = await startLocalhostServer({
        file_id: artifact.id,
        html: previewHtml,
        title: artifact.title,
      })
      if (res && res.url) {
        setServerUrl(res.url)
        window.open(res.url, '_blank', 'noopener,noreferrer')
      }
    } catch (err) {
      setHostError(err instanceof Error ? err.message : 'Could not launch localhost server')
    } finally {
      setIsHosting(false)
    }
  }

  return (
    <div
      className={`flex flex-col border-l border-white/[0.08] bg-[#0c0c0f] text-zinc-200 transition-all duration-300 ${
        isFullscreen
          ? 'fixed inset-0 z-50 w-screen h-screen'
          : 'relative h-full w-full'
      }`}
    >
      {/* Top Header Bar */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.08] bg-[#121216] px-4 backdrop-blur-xl">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="grid size-8 place-items-center rounded-lg border border-amber-500/20 bg-amber-500/10 text-amber-400">
            {isPreviewable ? <Globe size={16} /> : <FileCode size={16} />}
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-caption sm:text-small font-medium text-zinc-100">
              {artifact.title || 'Artifact'}
            </h2>
            <div className="flex items-center gap-1.5 text-[10px] text-zinc-400 font-mono">
              <span className="uppercase text-amber-400/90">{artifact.language}</span>
              <span>•</span>
              <span>{lines.length} lines</span>
            </div>
          </div>
        </div>

        {/* Viewport Toggles (Active only in Preview mode) */}
        {viewMode === 'preview' && isPreviewable && (
          <div className="hidden md:flex items-center rounded-lg border border-white/[0.08] bg-black/40 p-0.5">
            <button
              type="button"
              onClick={() => setViewport('desktop')}
              title="Desktop Viewport (100%)"
              className={`flex items-center gap-1 rounded-md px-2 py-1 text-micro transition ${
                viewport === 'desktop'
                  ? 'bg-white/10 text-white font-medium shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              <Monitor size={12} />
              <span>Desktop</span>
            </button>
            <button
              type="button"
              onClick={() => setViewport('tablet')}
              title="Tablet Viewport (768px)"
              className={`flex items-center gap-1 rounded-md px-2 py-1 text-micro transition ${
                viewport === 'tablet'
                  ? 'bg-white/10 text-white font-medium shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              <Tablet size={12} />
              <span>Tablet</span>
            </button>
            <button
              type="button"
              onClick={() => setViewport('mobile')}
              title="Mobile Viewport (390px)"
              className={`flex items-center gap-1 rounded-md px-2 py-1 text-micro transition ${
                viewport === 'mobile'
                  ? 'bg-white/10 text-white font-medium shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              <Smartphone size={12} />
              <span>Mobile</span>
            </button>
          </div>
        )}

        {/* View Mode & Actions */}
        <div className="flex items-center gap-1.5">
          {isPreviewable && (
            <div className="flex rounded-lg border border-white/[0.08] bg-black/40 p-0.5">
              <button
                type="button"
                onClick={() => setViewMode('preview')}
                className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-micro font-medium transition ${
                  viewMode === 'preview'
                    ? 'bg-amber-500/20 text-amber-200 border border-amber-500/30'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Eye size={12} />
                <span>Preview</span>
              </button>
              <button
                type="button"
                onClick={() => setViewMode('code')}
                className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-micro font-medium transition ${
                  viewMode === 'code'
                    ? 'bg-amber-500/20 text-amber-200 border border-amber-500/30'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Code2 size={12} />
                <span>Code</span>
              </button>
            </div>
          )}

          {viewMode === 'preview' && isPreviewable && (
            <>
              <button
                type="button"
                onClick={() => setReloadKey((k) => k + 1)}
                title="Reload preview"
                className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
              >
                <RotateCw size={13} />
              </button>
              <button
                type="button"
                onClick={handleRunLocalhost}
                disabled={isHosting}
                title={serverUrl ? `Live on ${serverUrl}` : 'Run live on local host server'}
                className="hidden sm:flex items-center gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-micro font-medium text-emerald-300 transition hover:bg-emerald-500/20"
              >
                <Server size={12} />
                <span>{serverUrl ? 'Live :8000' : 'Localhost'}</span>
              </button>
              <button
                type="button"
                onClick={handleOpenTab}
                title="Open in new browser tab"
                className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
              >
                <ExternalLink size={13} />
              </button>
            </>
          )}

          <button
            type="button"
            onClick={handleCopy}
            title="Copy code to clipboard"
            className="flex items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.04] px-2.5 py-1 text-micro text-zinc-300 transition hover:bg-white/[0.08] hover:text-white"
          >
            {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
            <span className="hidden sm:inline">{copied ? 'Copied' : 'Copy'}</span>
          </button>

          <button
            type="button"
            onClick={handleDownload}
            title="Download artifact file"
            className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
          >
            <Download size={13} />
          </button>

          <button
            type="button"
            onClick={() => setIsFullscreen(!isFullscreen)}
            title={isFullscreen ? 'Exit fullscreen' : 'Expand to fullscreen'}
            className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
          >
            {isFullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </button>

          <button
            type="button"
            onClick={onClose}
            title="Close Artifact Panel"
            className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-rose-500/20 hover:text-rose-200"
          >
            <X size={15} />
          </button>
        </div>
      </header>

      {/* Artifact History Pill Tabs (if multiple) */}
      {artifactsHistory.length > 1 && (
        <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-white/[0.06] bg-[#09090c] px-4 py-1.5 scrollbar-none">
          <span className="text-[10px] uppercase tracking-wider text-zinc-500 font-medium mr-1">
            Artifacts:
          </span>
          {artifactsHistory.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectArtifact?.(item)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-0.5 text-micro transition ${
                item.id === artifact.id
                  ? 'border border-amber-500/30 bg-amber-500/15 text-amber-200 font-medium'
                  : 'border border-white/[0.06] bg-white/[0.02] text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200'
              }`}
            >
              <FileCode size={10} className={item.id === artifact.id ? 'text-amber-400' : 'text-zinc-500'} />
              <span className="max-w-[130px] truncate">{item.title}</span>
            </button>
          ))}
        </div>
      )}

      {/* Error banner */}
      {hostError && (
        <div className="flex items-center gap-2 border-b border-rose-500/20 bg-rose-950/40 px-4 py-2 text-micro text-rose-300">
          <AlertCircle size={12} className="shrink-0 text-rose-400" />
          <span>{hostError}</span>
        </div>
      )}

      {/* Main Workspace Body */}
      <div className="relative min-h-0 flex-1 overflow-hidden bg-[#09090c]">
        {viewMode === 'preview' && isPreviewable ? (
          <div className="flex h-full w-full items-center justify-center overflow-auto p-2 sm:p-4 bg-zinc-950/80">
            {viewport === 'desktop' && (
              <iframe
                ref={iframeRef}
                key={reloadKey}
                srcDoc={previewHtml}
                title={artifact.title}
                sandbox="allow-scripts allow-forms allow-modals allow-popups"
                className="h-full w-full rounded-xl border border-white/[0.08] bg-white shadow-2xl transition-all"
              />
            )}

            {viewport === 'tablet' && (
              <div className="relative h-full w-[768px] max-w-full overflow-hidden rounded-2xl border-[10px] border-zinc-800 bg-white shadow-2xl ring-1 ring-white/10">
                <iframe
                  ref={iframeRef}
                  key={reloadKey}
                  srcDoc={previewHtml}
                  title={artifact.title}
                  sandbox="allow-scripts allow-forms allow-modals allow-popups"
                  className="h-full w-full bg-white"
                />
              </div>
            )}

            {viewport === 'mobile' && (
              <div className="relative h-[680px] w-[390px] max-w-full overflow-hidden rounded-[40px] border-[10px] border-zinc-800 bg-white shadow-2xl ring-1 ring-white/10">
                <div className="absolute top-2.5 left-1/2 z-20 flex h-4 w-24 -translate-x-1/2 items-center justify-center rounded-full bg-zinc-900">
                  <div className="h-1 w-8 rounded-full bg-zinc-700" />
                </div>
                <iframe
                  ref={iframeRef}
                  key={reloadKey}
                  srcDoc={previewHtml}
                  title={artifact.title}
                  sandbox="allow-scripts allow-forms allow-modals allow-popups"
                  className="h-full w-full bg-white pt-6"
                />
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-full w-full overflow-auto p-4 font-mono text-[13px] leading-relaxed select-text">
            <div className="flex min-w-full">
              {/* Line Numbers */}
              <div
                className="select-none pr-4 text-right text-zinc-600 font-mono text-micro border-r border-white/[0.06]"
                aria-hidden="true"
              >
                {lines.map((_, i) => (
                  <div key={i} className="leading-6">
                    {i + 1}
                  </div>
                ))}
              </div>

              {/* Code Content */}
              <pre className="flex-1 overflow-x-auto pl-4 text-zinc-200 leading-6 font-mono text-micro">
                <code>{artifact.content}</code>
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
