import {
  LOGO_VIEWBOX,
  LOGO_STAR_PATH,
  LOGO_ORBIT_PATH,
  LOGO_MOON_PATH,
  LOGO_SPARKLES_PATH,
  LOGO_STRUTS_PATH,
  LOGO_FACETS_PATH,
} from './logoPaths'

/**
 * Pentagon Brand Mark: Pure Mathematical SVG Vector.
 * Vectorized with subpixel precision from the official Pentagon brand mark.
 * Structurally split into semantic layers:
 *   - Celestial Crown: Compass Star, Stationary Outer Halo, Rotating Inner Orbit, Crescent Moon, Radiant Sparkles
 *   - 3D Space Globe: Polyhedral Wireframe Struts, Bevels, Translucent Glass Facets
 *
 * Equipped with dual-circle orbital rotation:
 *   - Outer circle remains still.
 *   - Inner circle rotates from left to right (clockwise): Fast on loading, Slow otherwise.
 */
export function Logomark({
  size = 20,
  className = '',
  opacity = 1,
  animated = true,
  loading = false,
}: {
  size?: number
  className?: string
  opacity?: number
  animated?: boolean
  loading?: boolean
}) {
  return (
    <svg
      viewBox={LOGO_VIEWBOX}
      width={size}
      height={size}
      role="presentation"
      aria-hidden="true"
      focusable="false"
      className={`logo-mark shrink-0 select-none ${animated ? 'logo-animated' : ''} ${loading ? 'logo-loading' : ''} ${className}`}
      style={{ opacity }}
    >
      <defs>
        <linearGradient id="pentagon-glass-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.38" />
          <stop offset="50%" stopColor="currentColor" stopOpacity="0.22" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.08" />
        </linearGradient>
        <radialGradient id="pentagon-star-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.25" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* 1. Translucent crystal glass facets with refractive depth */}
      <g className={animated ? 'logo-facets' : ''}>
        <path
          d={LOGO_FACETS_PATH}
          fill="url(#pentagon-glass-gradient)"
          fillRule="evenodd"
        />
      </g>

      {/* 2. Polyhedral 3D crystal struts & bevels */}
      <g className={animated ? 'logo-globe' : ''}>
        <path
          d={LOGO_STRUTS_PATH}
          fill="currentColor"
          fillRule="evenodd"
          opacity={0.72}
        />
      </g>

      {/* Outer Circle: Remains completely STILL at all times */}
      <circle
        cx="255"
        cy="79"
        r="54"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeOpacity={loading ? 0.38 : 0.24}
        className="logo-outer-circle"
      />

      {/* 3. Celestial Crown (Star, Halo Orbit, Moon, Sparkles) */}
      <g className={animated && !loading ? 'logo-crown' : ''}>
        {/* Soft aura glow centered on compass star (255, 79) */}
        <circle cx="255" cy="79" r="56" fill="url(#pentagon-star-glow)" />

        {/* Inner Circle: Rotates from left to right (clockwise) */}
        {/* Fast on loading animation (~1.1s), slow otherwise (~22s) */}
        <g
          className={`logo-inner-circle ${
            loading ? 'logo-loading-fast text-emerald-400' : animated ? 'logo-orbit-slow' : ''
          }`}
          style={{ transformOrigin: '255px 79px', transformBox: 'view-box' }}
        >
          <circle
            cx="255"
            cy="79"
            r="46.5"
            fill="none"
            stroke="currentColor"
            strokeWidth={loading ? 1.8 : 1.4}
            strokeOpacity={loading ? 0.95 : 0.65}
            strokeDasharray={loading ? '28 8 14 6' : '26 8 12 6'}
          />
          <path
            d={LOGO_ORBIT_PATH}
            fill="currentColor"
            fillRule="evenodd"
            opacity={loading ? 0.95 : 0.6}
          />
        </g>

        {/* Crescent Moon */}
        <g className={animated ? 'logo-moon' : ''}>
          <path
            d={LOGO_MOON_PATH}
            fill="currentColor"
            fillRule="evenodd"
            opacity={0.8}
          />
        </g>

        {/* Radiant Sparkles / Starlets */}
        <g className={animated ? 'logo-sparkles' : ''}>
          <path
            d={LOGO_SPARKLES_PATH}
            fill="currentColor"
            fillRule="evenodd"
            opacity={0.85}
          />
        </g>

        {/* 8-Pointed Celestial Compass Star */}
        <g className={animated ? 'logo-star' : ''}>
          <path
            d={LOGO_STAR_PATH}
            fill="currentColor"
            fillRule="evenodd"
            opacity={0.88}
          />
        </g>
      </g>
    </svg>
  )
}

export function LogomarkBadge({
  size = 34,
  className = '',
  label,
  opacity = 1,
  animated = true,
  loading = false,
  withRings,
}: {
  size?: number
  className?: string
  label?: string
  opacity?: number
  animated?: boolean
  loading?: boolean
  withRings?: boolean
}) {
  // Show orbital frame rings if explicitly requested, when loading, or for centerpiece badges (size >= 48)
  const showRings = withRings ?? (size >= 48 || loading)

  return (
    <span
      className={`relative grid shrink-0 place-items-center group ${className}`}
      style={{ width: size, height: size }}
    >
      {showRings && (
        <>
          {/* Outer Circle: Remains completely STILL */}
          <span
            className="absolute inset-0 rounded-full border border-white/[0.12] pointer-events-none"
            aria-hidden="true"
          />

          {/* Inner Circle: Rotates from left to right (clockwise) */}
          {/* Fast rotation on loading (~1.2s), slow orbit otherwise (~20s) */}
          <span
            className={`absolute inset-[3px] rounded-full pointer-events-none ${
              loading
                ? 'border-[1.5px] border-emerald-400 border-t-transparent shadow-[0_0_12px_rgba(52,211,153,0.35)] animate-spin-fast'
                : 'border border-dashed border-white/20 border-t-emerald-400/60 animate-spin-slow'
            }`}
            aria-hidden="true"
          />
        </>
      )}

      <Logomark
        size={showRings ? Math.round(size * 0.74) : size}
        opacity={opacity}
        animated={animated}
        loading={loading}
        className={`${
          loading
            ? 'text-emerald-400 drop-shadow-[0_0_14px_rgba(52,211,153,0.45)]'
            : 'text-zinc-100 drop-shadow-[0_0_12px_rgba(255,255,255,0.22)] group-hover:drop-shadow-[0_0_18px_rgba(255,255,255,0.45)]'
        } transition-all duration-300 group-hover:scale-105`}
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}