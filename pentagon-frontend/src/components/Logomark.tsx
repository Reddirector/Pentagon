/**
 * Pentagon Brand Mark: Pure Mathematical SVG Vector.
 * Hand-crafted faceted pentagonal prism with central neural core.
 * No PNG raster or autotracing dependencies.
 */

export function Logomark({
  size = 20,
  className = '',
  opacity = 1,
}: {
  size?: number
  className?: string
  opacity?: number
}) {
  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      role="presentation"
      aria-hidden="true"
      focusable="false"
      className={`logo-mark shrink-0 select-none ${className}`}
      style={{ opacity }}
    >
      <defs>
        <linearGradient id="pentagon-facet-key" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="currentColor" stopOpacity="1" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.75" />
        </linearGradient>
        <linearGradient id="pentagon-facet-direct" x1="100%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.88" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.65" />
        </linearGradient>
      </defs>

      {/* Outer Structural Pentagon Perimeter */}
      <polygon
        points="24,3.5 44,18 36.3,41.5 11.7,41.5 4,18"
        fill="currentColor"
        fillOpacity="0.1"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeOpacity="0.85"
      />

      {/* 5 Dimensional Facets Radiating from Vertices to Center (24, 24.5) */}
      {/* Top-Right Facet */}
      <polygon points="24,3.5 44,18 24,24.5" fill="url(#pentagon-facet-direct)" fillOpacity="0.85" />
      {/* Bottom-Right Facet */}
      <polygon points="44,18 36.3,41.5 24,24.5" fill="currentColor" fillOpacity="0.55" />
      {/* Bottom Facet */}
      <polygon points="36.3,41.5 11.7,41.5 24,24.5" fill="currentColor" fillOpacity="0.4" />
      {/* Bottom-Left Facet */}
      <polygon points="11.7,41.5 4,18 24,24.5" fill="currentColor" fillOpacity="0.65" />
      {/* Top-Left Facet */}
      <polygon points="4,18 24,3.5 24,24.5" fill="url(#pentagon-facet-key)" fillOpacity="0.95" />

      {/* Internal Precision Seam Lines */}
      <line x1="24" y1="3.5" x2="24" y2="24.5" stroke="currentColor" strokeWidth="0.75" strokeOpacity="0.6" />
      <line x1="44" y1="18" x2="24" y2="24.5" stroke="currentColor" strokeWidth="0.75" strokeOpacity="0.45" />
      <line x1="36.3" y1="41.5" x2="24" y2="24.5" stroke="currentColor" strokeWidth="0.75" strokeOpacity="0.35" />
      <line x1="11.7" y1="41.5" x2="24" y2="24.5" stroke="currentColor" strokeWidth="0.75" strokeOpacity="0.35" />
      <line x1="4" y1="18" x2="24" y2="24.5" stroke="currentColor" strokeWidth="0.75" strokeOpacity="0.55" />

      {/* Central Aperture Nexus (Inner Pentagon Core) */}
      <polygon
        points="24,17.5 30.7,22.3 28.1,30.2 19.9,30.2 17.3,22.3"
        fill="#09090b"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <circle cx="24" cy="24.5" r="1.6" fill="currentColor" />
    </svg>
  )
}

export function LogomarkBadge({
  size = 34,
  className = '',
  label,
  opacity = 1,
}: {
  size?: number
  className?: string
  label?: string
  opacity?: number
}) {
  return (
    <span
      className={`grid shrink-0 place-items-center ${className}`}
      style={{ width: size, height: size }}
    >
      <Logomark
        size={size}
        opacity={opacity}
        className="text-emerald-400 drop-shadow-[0_0_12px_rgba(52,211,153,0.4)]"
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}