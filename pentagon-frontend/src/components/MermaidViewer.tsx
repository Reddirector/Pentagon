import { useEffect, useId, useRef, useState } from 'react'
import { AlertCircle, Check, Copy, Maximize2 } from 'lucide-react'
import mermaid from 'mermaid'

// Initialize mermaid once with clean modern dark theme matching Claude's aesthetic
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    darkMode: true,
    background: '#121216',
    primaryColor: '#d97706',
    primaryTextColor: '#f4f4f6',
    primaryBorderColor: '#b45309',
    lineColor: '#71717a',
    secondaryColor: '#1f1f24',
    tertiaryColor: '#18181b',
    fontFamily: 'Inter, system-ui, sans-serif',
    fontSize: '13px',
  },
  securityLevel: 'loose',
  flowchart: { curve: 'basis', htmlLabels: true },
})

export function MermaidViewer({ chart, onOpenArtifact }: { chart: string; onOpenArtifact?: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [svgHtml, setSvgHtml] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const uniqueId = useId().replace(/:/g, '_')

  useEffect(() => {
    let isMounted = true
    const renderChart = async () => {
      try {
        setError(null)
        const cleanChart = chart.trim()
        if (!cleanChart) return
        const { svg } = await mermaid.render(`mermaid_${uniqueId}`, cleanChart)
        if (isMounted) {
          setSvgHtml(svg)
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to render diagram')
        }
      }
    }

    renderChart()
    return () => {
      isMounted = false
    }
  }, [chart, uniqueId])

  const handleCopySvg = async () => {
    if (!svgHtml) return
    await navigator.clipboard.writeText(svgHtml)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (error) {
    return (
      <div className="my-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.08] p-3 text-caption text-amber-200">
        <div className="flex items-center gap-1.5 font-medium">
          <AlertCircle size={13} className="text-amber-400" />
          <span>Diagram syntax error</span>
        </div>
        <pre className="mt-1.5 max-h-24 overflow-x-auto text-[11px] text-zinc-400 font-mono">{error}</pre>
      </div>
    )
  }

  return (
    <div className="group relative my-4 overflow-hidden rounded-xl border border-white/[0.1] bg-[#121216] shadow-[0_8px_30px_rgba(0,0,0,0.5)]">
      {/* Chrome Header */}
      <div className="flex items-center justify-between border-b border-white/[0.07] bg-white/[0.02] px-3.5 py-2 text-micro uppercase tracking-wider text-zinc-400">
        <span className="font-semibold text-amber-400/90 flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-amber-400" />
          Mermaid Diagram
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={handleCopySvg}
            className="flex items-center gap-1 rounded-md px-2 py-0.5 text-micro normal-case tracking-normal text-zinc-400 transition hover:bg-white/[0.07] hover:text-white"
            title="Copy SVG code"
          >
            {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
            <span>{copied ? 'Copied' : 'SVG'}</span>
          </button>
          {onOpenArtifact && (
            <button
              type="button"
              onClick={onOpenArtifact}
              className="flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-micro font-medium normal-case tracking-normal text-amber-300 transition hover:bg-amber-500/25"
              title="Open in Artifact Panel"
            >
              <Maximize2 size={11} />
              <span>Artifact</span>
            </button>
          )}
        </div>
      </div>

      {/* Rendered SVG */}
      <div
        ref={containerRef}
        className="overflow-x-auto p-4 flex justify-center [&_svg]:max-w-full [&_svg]:h-auto select-none"
        dangerouslySetInnerHTML={{ __html: svgHtml }}
      />
    </div>
  )
}
