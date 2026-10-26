import { useState } from 'react'
import {
  Sparkles,
  FileText,
  FileSpreadsheet,
  Presentation,
  Globe,
  Code2,
  Eye,
  ArrowUpRight,
} from 'lucide-react'

export interface StudioCardItem {
  id: string
  category: 'docs' | 'sheets' | 'slides' | 'research' | 'code' | 'vision'
  badge: string
  formatTag: string
  title: string
  subtitle: string
  prompt: string
  glowColor: string
  accentColor: string
  renderArtwork: () => React.ReactNode
}

const STUDIO_ITEMS: StudioCardItem[] = [
  {
    id: 'document-forge',
    category: 'docs',
    badge: 'Executive Docs',
    formatTag: '.docx',
    title: 'Document Forge',
    subtitle: 'Business proposals & whitepapers',
    prompt: 'Create a comprehensive 5-page enterprise SaaS business proposal with executive summary, market analysis, financial projections, and implementation roadmap as a Word document (.docx).',
    glowColor: 'rgba(52, 211, 153, 0.25)',
    accentColor: '#34d399',
    renderArtwork: () => (
      <svg viewBox="0 0 320 180" className="size-full select-none" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="doc-grad-1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#1e293b" />
            <stop offset="100%" stopColor="#0f172a" />
          </linearGradient>
          <linearGradient id="doc-grad-2" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#059669" stopOpacity="0.2" />
          </linearGradient>
          <linearGradient id="doc-gold-seal" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#fde047" />
            <stop offset="100%" stopColor="#d97706" />
          </linearGradient>
          <filter id="doc-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="8" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Ambient background bloom */}
        <ellipse cx="160" cy="90" rx="90" ry="50" fill="url(#doc-grad-2)" opacity="0.3" filter="url(#doc-glow)" />

        {/* Back page stack */}
        <rect x="100" y="32" width="130" height="120" rx="10" fill="#0f172a" stroke="rgba(255,255,255,0.08)" strokeWidth="1" transform="rotate(-6 165 92)" />
        <rect x="96" y="30" width="130" height="120" rx="10" fill="#1e293b" stroke="rgba(255,255,255,0.12)" strokeWidth="1" transform="rotate(3 161 90)" />

        {/* Hero Front Page */}
        <g filter="drop-shadow(0 12px 24px rgba(0,0,0,0.6))">
          <rect x="98" y="26" width="124" height="124" rx="10" fill="url(#doc-grad-1)" stroke="rgba(52,211,153,0.35)" strokeWidth="1.2" />

          {/* Header block with emerald accent */}
          <rect x="114" y="42" width="46" height="6" rx="3" fill="#34d399" />
          <rect x="114" y="53" width="76" height="4" rx="2" fill="rgba(255,255,255,0.4)" />
          <rect x="114" y="61" width="62" height="4" rx="2" fill="rgba(255,255,255,0.2)" />

          {/* Body wireframe lines */}
          <line x1="114" y1="76" x2="206" y2="76" stroke="rgba(255,255,255,0.18)" strokeWidth="3" strokeLinecap="round" />
          <line x1="114" y1="86" x2="198" y2="86" stroke="rgba(255,255,255,0.14)" strokeWidth="3" strokeLinecap="round" />
          <line x1="114" y1="96" x2="206" y2="96" stroke="rgba(255,255,255,0.18)" strokeWidth="3" strokeLinecap="round" />
          <line x1="114" y1="106" x2="175" y2="106" stroke="rgba(255,255,255,0.14)" strokeWidth="3" strokeLinecap="round" />

          {/* Golden embossed wax seal */}
          <circle cx="194" cy="122" r="14" fill="url(#doc-gold-seal)" opacity="0.95" filter="drop-shadow(0 2px 6px rgba(217,119,6,0.6))" />
          <circle cx="194" cy="122" r="11" fill="none" stroke="#fef08a" strokeWidth="1.5" strokeDasharray="3 2" />
          <path d="M194 116L196 120H200L197 122L198 126L194 123.5L190 126L191 122L188 120H192L194 116Z" fill="#fff" />
        </g>
      </svg>
    ),
  },
  {
    id: 'financial-matrix',
    category: 'sheets',
    badge: 'Financial Model',
    formatTag: '.xlsx',
    title: 'Financial Matrix',
    subtitle: 'Revenue models & unit economics',
    prompt: 'Build a multi-year SaaS financial model spreadsheet with monthly revenue forecasts, customer cohorts, CAC/LTV calculations, and EBITDA summaries (.xlsx).',
    glowColor: 'rgba(16, 185, 129, 0.3)',
    accentColor: '#10b981',
    renderArtwork: () => (
      <svg viewBox="0 0 320 180" className="size-full select-none" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="bar-grad-1" x1="0%" y1="100%" x2="0%" y2="0%">
            <stop offset="0%" stopColor="#064e3b" />
            <stop offset="100%" stopColor="#34d399" />
          </linearGradient>
          <linearGradient id="bar-grad-2" x1="0%" y1="100%" x2="0%" y2="0%">
            <stop offset="0%" stopColor="#047857" />
            <stop offset="100%" stopColor="#6ee7b7" />
          </linearGradient>
          <linearGradient id="sheet-bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#0f172a" />
            <stop offset="100%" stopColor="#020617" />
          </linearGradient>
          <filter id="chart-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Ambient green bloom */}
        <ellipse cx="160" cy="110" rx="100" ry="40" fill="#10b981" opacity="0.18" filter="url(#chart-glow)" />

        {/* 3D Isometric Base Board */}
        <g transform="translate(160 100) scale(1 0.58) rotate(45)">
          {/* Grid lines */}
          <rect x="-70" y="-70" width="140" height="140" rx="16" fill="url(#sheet-bg)" stroke="rgba(52,211,153,0.3)" strokeWidth="1.5" />
          <path d="M-70 -25 H70 M-70 20 H70 M-25 -70 V70 M20 -70 V70" stroke="rgba(255,255,255,0.06)" strokeWidth="1" />

          {/* Bar 1 */}
          <rect x="-50" y="-40" width="22" height="32" rx="4" fill="url(#bar-grad-1)" filter="drop-shadow(0 0 8px rgba(52,211,153,0.4))" />
          {/* Bar 2 */}
          <rect x="-16" y="-55" width="22" height="60" rx="4" fill="url(#bar-grad-1)" filter="drop-shadow(0 0 10px rgba(52,211,153,0.5))" />
          {/* Bar 3 */}
          <rect x="18" y="-70" width="22" height="90" rx="4" fill="url(#bar-grad-2)" filter="drop-shadow(0 0 14px rgba(110,231,183,0.7))" />
        </g>

        {/* Ascending trend line with glowing beacons */}
        <path d="M75 125 Q130 95 165 72 T245 42" stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" fill="none" filter="drop-shadow(0 0 6px #34d399)" />
        <circle cx="75" cy="125" r="3.5" fill="#fff" />
        <circle cx="165" cy="72" r="4.5" fill="#6ee7b7" filter="drop-shadow(0 0 4px #34d399)" />
        <circle cx="245" cy="42" r="6" fill="#fff" filter="drop-shadow(0 0 8px #34d399)" />
      </svg>
    ),
  },
  {
    id: 'keynote-studio',
    category: 'slides',
    badge: 'Pitch Deck',
    formatTag: '.pptx',
    title: 'Keynote Cinema',
    subtitle: 'Investor decks & executive presentations',
    prompt: 'Generate an engaging 10-slide startup pitch deck presentation covering the problem, solution, market size, product demo, unit economics, and team (.pptx).',
    glowColor: 'rgba(168, 85, 247, 0.28)',
    accentColor: '#a855f7',
    renderArtwork: () => (
      <svg viewBox="0 0 320 180" className="size-full select-none" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="slide-prism" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#a855f7" />
            <stop offset="50%" stopColor="#6366f1" />
            <stop offset="100%" stopColor="#06b6d4" />
          </linearGradient>
          <linearGradient id="slide-card-bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#1e1b4b" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#09090b" stopOpacity="0.95" />
          </linearGradient>
          <filter id="slide-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="10" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Ambient violet-indigo flare */}
        <ellipse cx="160" cy="85" rx="95" ry="45" fill="url(#slide-prism)" opacity="0.32" filter="url(#slide-glow)" />

        {/* Perspective background slide */}
        <rect x="76" y="32" width="168" height="98" rx="10" fill="#18181b" stroke="rgba(255,255,255,0.08)" strokeWidth="1" transform="rotate(-4 160 81)" />

        {/* Hero 16:9 Cinema Slide */}
        <g filter="drop-shadow(0 14px 28px rgba(0,0,0,0.65))">
          <rect x="80" y="36" width="160" height="94" rx="10" fill="url(#slide-card-bg)" stroke="rgba(168,85,247,0.4)" strokeWidth="1.2" />

          {/* Screen highlight / top gloss */}
          <path d="M81 46 C110 40, 210 40, 239 46 V37 C239 36.5, 238.5 36, 238 36 H82 C81.5 36, 81 36.5, 81 37 Z" fill="rgba(255,255,255,0.08)" />

          {/* Presentation Slide Content Elements */}
          <rect x="96" y="50" width="34" height="5" rx="2.5" fill="#c084fc" />
          <rect x="96" y="60" width="70" height="8" rx="2" fill="#ffffff" />
          <rect x="96" y="73" width="90" height="3" rx="1.5" fill="rgba(255,255,255,0.35)" />
          <rect x="96" y="79" width="75" height="3" rx="1.5" fill="rgba(255,255,255,0.2)" />

          {/* Visual chart graphic inside slide */}
          <rect x="186" y="58" width="40" height="40" rx="8" fill="rgba(168,85,247,0.12)" stroke="rgba(168,85,247,0.3)" />
          <circle cx="206" cy="78" r="12" fill="none" stroke="#a855f7" strokeWidth="2" strokeDasharray="50 25" />
          <circle cx="206" cy="78" r="6" fill="#38bdf8" />
        </g>
      </svg>
    ),
  },
  {
    id: 'deep-intelligence',
    category: 'research',
    badge: 'Frontier AI',
    formatTag: 'Web Search',
    title: 'Deep Intelligence',
    subtitle: 'Multi-query grounded web synthesis',
    prompt: 'Perform deep research on current 2026 breakthroughs in agentic AI architectures and multi-step reasoning models, synthesizing verified findings and citations.',
    glowColor: 'rgba(56, 189, 248, 0.28)',
    accentColor: '#38bdf8',
    renderArtwork: () => (
      <svg viewBox="0 0 320 180" className="size-full select-none" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="cosmic-blue" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#38bdf8" />
            <stop offset="100%" stopColor="#0369a1" />
          </linearGradient>
          <radialGradient id="globe-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.4" />
            <stop offset="60%" stopColor="#0284c7" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#082f49" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient cosmic aura */}
        <circle cx="160" cy="90" r="65" fill="url(#globe-core)" />

        {/* Outer orbital rings */}
        <circle cx="160" cy="90" r="70" stroke="rgba(56,189,248,0.18)" strokeWidth="1" strokeDasharray="8 6" />
        <ellipse cx="160" cy="90" rx="80" ry="32" stroke="rgba(56,189,248,0.4)" strokeWidth="1.2" transform="rotate(-25 160 90)" />
        <ellipse cx="160" cy="90" rx="80" ry="32" stroke="rgba(52,211,153,0.3)" strokeWidth="1" transform="rotate(35 160 90)" />

        {/* Planet core wireframe */}
        <circle cx="160" cy="90" r="38" fill="#082f49" stroke="#38bdf8" strokeWidth="1.5" />
        <ellipse cx="160" cy="90" rx="16" ry="38" stroke="rgba(56,189,248,0.4)" strokeWidth="1" />
        <line x1="122" y1="90" x2="198" y2="90" stroke="rgba(56,189,248,0.4)" strokeWidth="1" />

        {/* Orbiting satellites / nodes */}
        <circle cx="218" cy="62" r="5" fill="#38bdf8" filter="drop-shadow(0 0 6px #38bdf8)" />
        <line x1="160" y1="90" x2="218" y2="62" stroke="rgba(56,189,248,0.4)" strokeDasharray="2 2" />

        <circle cx="106" cy="118" r="4" fill="#34d399" filter="drop-shadow(0 0 6px #34d399)" />
        <line x1="160" y1="90" x2="106" y2="118" stroke="rgba(52,211,153,0.4)" strokeDasharray="2 2" />

        <circle cx="160" cy="20" r="3" fill="#ffffff" filter="drop-shadow(0 0 4px #fff)" />
      </svg>
    ),
  },
  {
    id: 'code-architecture',
    category: 'code',
    badge: 'Code Engine',
    formatTag: 'Python / TS',
    title: 'Code Studio',
    subtitle: 'System architecture, algorithms & review',
    prompt: 'Architect a clean, scalable distributed queue system in TypeScript with Redis pub/sub, worker threads, backpressure handling, and comprehensive unit tests.',
    glowColor: 'rgba(52, 211, 153, 0.28)',
    accentColor: '#34d399',
    renderArtwork: () => (
      <svg viewBox="0 0 320 180" className="size-full select-none" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="term-bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#0d1117" />
            <stop offset="100%" stopColor="#05080c" />
          </linearGradient>
        </defs>

        {/* Terminal Window */}
        <g filter="drop-shadow(0 14px 28px rgba(0,0,0,0.7))">
          <rect x="70" y="30" width="180" height="110" rx="10" fill="url(#term-bg)" stroke="rgba(52,211,153,0.3)" strokeWidth="1.2" />

          {/* Terminal Window Header */}
          <rect x="70" y="30" width="180" height="22" rx="10" fill="rgba(255,255,255,0.03)" />
          <circle cx="86" cy="41" r="3" fill="#f87171" opacity="0.8" />
          <circle cx="96" cy="41" r="3" fill="#facc15" opacity="0.8" />
          <circle cx="106" cy="41" r="3" fill="#4ade80" opacity="0.8" />
          <rect x="130" y="38" width="60" height="6" rx="3" fill="rgba(255,255,255,0.12)" />

          {/* Syntax Lines */}
          <g transform="translate(85 64)">
            {/* line 1: const server = ... */}
            <rect x="0" y="0" width="28" height="4" rx="2" fill="#38bdf8" />
            <rect x="34" y="0" width="40" height="4" rx="2" fill="#a7f3d0" />
            <rect x="80" y="0" width="14" height="4" rx="2" fill="#fff" />
            <rect x="100" y="0" width="36" height="4" rx="2" fill="#34d399" />

            {/* line 2: indent */}
            <rect x="14" y="12" width="22" height="4" rx="2" fill="#c084fc" />
            <rect x="42" y="12" width="56" height="4" rx="2" fill="rgba(255,255,255,0.5)" />

            {/* line 3: return await ... */}
            <rect x="14" y="24" width="32" height="4" rx="2" fill="#f43f5e" />
            <rect x="52" y="24" width="46" height="4" rx="2" fill="#38bdf8" />
            <rect x="104" y="24" width="26" height="4" rx="2" fill="#34d399" />

            {/* line 4: } */}
            <rect x="0" y="36" width="12" height="4" rx="2" fill="#38bdf8" />

            {/* Blinking Cursor */}
            <rect x="18" y="35" width="6" height="6" fill="#34d399" filter="drop-shadow(0 0 4px #34d399)" />
          </g>

          {/* Ambient code tags */}
          <text x="216" y="124" fill="rgba(52,211,153,0.3)" fontFamily="monospace" fontSize="18" fontWeight="bold">&lt;/&gt;</text>
        </g>
      </svg>
    ),
  },
  {
    id: 'vision-lab',
    category: 'vision',
    badge: 'Vision AI',
    formatTag: 'Visual RAG',
    title: 'Vision Studio',
    subtitle: 'Multimodal image & diagram parsing',
    prompt: 'Inspect and break down the visual hierarchy, layout architecture, typography, color harmony, and accessibility tokens of an uploaded design.',
    glowColor: 'rgba(251, 191, 36, 0.25)',
    accentColor: '#fbbf24',
    renderArtwork: () => (
      <svg viewBox="0 0 320 180" className="size-full select-none" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="aperture-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#fbbf24" stopOpacity="0.5" />
            <stop offset="60%" stopColor="#d97706" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#451a03" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient golden aura */}
        <circle cx="160" cy="90" r="60" fill="url(#aperture-core)" />

        {/* Viewfinder Target Brackets */}
        <path d="M100 60 H116 M100 60 V76" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round" />
        <path d="M220 60 H204 M220 60 V76" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round" />
        <path d="M100 120 H116 M100 120 V104" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round" />
        <path d="M220 120 H204 M220 120 V104" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round" />

        {/* Aperture Iris Concentric Rings */}
        <circle cx="160" cy="90" r="42" stroke="rgba(251,191,36,0.3)" strokeWidth="1.2" strokeDasharray="6 4" />
        <circle cx="160" cy="90" r="30" stroke="rgba(251,191,36,0.5)" strokeWidth="1.5" />
        <circle cx="160" cy="90" r="16" fill="#18181b" stroke="#fbbf24" strokeWidth="2" filter="drop-shadow(0 0 8px rgba(251,191,36,0.6))" />
        <circle cx="160" cy="90" r="6" fill="#fff" />

        {/* Crosshair ticks */}
        <line x1="160" y1="42" x2="160" y2="52" stroke="#fbbf24" strokeWidth="1.5" />
        <line x1="160" y1="128" x2="160" y2="138" stroke="#fbbf24" strokeWidth="1.5" />
        <line x1="112" y1="90" x2="122" y2="90" stroke="#fbbf24" strokeWidth="1.5" />
        <line x1="198" y1="90" x2="208" y2="90" stroke="#fbbf24" strokeWidth="1.5" />
      </svg>
    ),
  },
]

export function VisualStudioGallery({
  onSelectPrompt,
}: {
  onSelectPrompt: (prompt: string) => void
}) {
  const [activeCategory, setActiveCategory] = useState<'all' | 'docs' | 'sheets' | 'slides' | 'research' | 'code' | 'vision'>('all')

  const filteredItems = activeCategory === 'all'
    ? STUDIO_ITEMS
    : STUDIO_ITEMS.filter((item) => item.category === activeCategory)

  const categories = [
    { id: 'all', label: 'All Studios', icon: Sparkles },
    { id: 'docs', label: 'Documents', icon: FileText },
    { id: 'sheets', label: 'Financials', icon: FileSpreadsheet },
    { id: 'slides', label: 'Keynotes', icon: Presentation },
    { id: 'research', label: 'Research', icon: Globe },
    { id: 'code', label: 'Code', icon: Code2 },
    { id: 'vision', label: 'Vision', icon: Eye },
  ] as const

  return (
    <div className="w-full max-w-4xl px-2 sm:px-4">
      {/* Visual Category Filter Bar */}
      <div className="mb-5 flex flex-wrap items-center justify-center gap-1.5 sm:gap-2">
        {categories.map((cat) => {
          const Icon = cat.icon
          const isActive = activeCategory === cat.id
          return (
            <button
              key={cat.id}
              type="button"
              onClick={() => setActiveCategory(cat.id)}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-micro font-medium transition duration-200 ${
                isActive
                  ? 'border border-emerald-400/50 bg-emerald-400/15 text-emerald-200 shadow-[0_0_16px_rgba(52,211,153,0.2)]'
                  : 'border border-white/[0.07] bg-white/[0.03] text-zinc-400 hover:border-white/[0.15] hover:bg-white/[0.06] hover:text-zinc-200'
              }`}
            >
              <Icon size={12} className={isActive ? 'text-emerald-400' : 'text-zinc-400'} />
              <span>{cat.label}</span>
            </button>
          )
        })}
      </div>

      {/* Visual Gallery Grid: 2 columns on desktop, 1 on phone */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 sm:gap-4">
        {filteredItems.map((item) => {
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectPrompt(item.prompt)}
              className="group relative flex flex-col overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-white/[0.04] to-black/60 p-0 text-left transition-all duration-300 ease-out hover:-translate-y-1 hover:border-emerald-400/40 hover:shadow-[0_16px_36px_rgba(0,0,0,0.7),0_0_24px_rgba(52,211,153,0.12)] active:translate-y-0"
            >
              {/* Top Artwork Canvas Header */}
              <div className="relative h-28 w-full overflow-hidden bg-[#090b10] border-b border-white/[0.06] transition duration-300 group-hover:bg-[#0c0f16]">
                <div
                  className="absolute inset-0 opacity-40 transition-opacity duration-300 group-hover:opacity-75"
                  style={{
                    background: `radial-gradient(circle at 50% 50%, ${item.glowColor} 0%, transparent 70%)`,
                  }}
                />
                <div className="relative size-full transition-transform duration-300 group-hover:scale-105">
                  {item.renderArtwork()}
                </div>

                {/* Format Pill Badge */}
                <div className="absolute right-2.5 top-2.5 flex items-center gap-1 rounded-md border border-white/[0.12] bg-black/60 px-2 py-0.5 font-mono text-[10px] text-zinc-300 backdrop-blur-md">
                  <span>{item.formatTag}</span>
                </div>
              </div>

              {/* Card Bottom Meta */}
              <div className="flex flex-1 flex-col justify-between p-3.5">
                <div>
                  <div className="flex items-center justify-between">
                    <span
                      className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400"
                      style={{ color: item.accentColor }}
                    >
                      {item.badge}
                    </span>
                    <ArrowUpRight
                      size={14}
                      className="text-zinc-500 opacity-0 transition-all duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:opacity-100 group-hover:text-emerald-300"
                    />
                  </div>
                  <h3 className="mt-1 text-small font-semibold text-zinc-100 transition duration-200 group-hover:text-white">
                    {item.title}
                  </h3>
                  <p className="mt-0.5 text-micro text-zinc-400 line-clamp-1">
                    {item.subtitle}
                  </p>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
