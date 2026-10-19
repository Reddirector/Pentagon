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
 *   - Celestial Crown: Compass Star, Orbit Halo Ring, Crescent Moon, Radiant Sparkles
 *   - 3D Space Globe: Polyhedral Wireframe Struts, Bevels, Translucent Glass Facets
 *
 * Fully modular and equipped with dedicated CSS hooks for custom keyframe animations.
 */
export function Logomark({
  size = 20,
  className = '',
  opacity = 1,
  animated = true,
}: {
  size?: number
  className?: string
  opacity?: number
  animated?: boolean
}) {
  return (
    <svg
      viewBox={LOGO_VIEWBOX}
      width={size}
      height={size}
      role="presentation"
      aria-hidden="true"
      focusable="false"
      className={`logo-mark shrink-0 select-none ${animated ? 'logo-animated' : ''} ${className}`}
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

      {/* 3. Celestial Crown (Star, Halo Orbit, Moon, Sparkles) */}
      <g className={animated ? 'logo-crown' : ''}>
        {/* Soft aura glow centered on compass star (255, 79) */}
        <circle cx="255" cy="79" r="54" fill="url(#pentagon-star-glow)" />

        {/* Orbit Ring / Celestial Halo */}
        <g className={animated ? 'logo-orbit' : ''}>
          <path
            d={LOGO_ORBIT_PATH}
            fill="currentColor"
            fillRule="evenodd"
            opacity={0.55}
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
}: {
  size?: number
  className?: string
  label?: string
  opacity?: number
  animated?: boolean
}) {
  return (
    <span
      className={`grid shrink-0 place-items-center group ${className}`}
      style={{ width: size, height: size }}
    >
      <Logomark
        size={size}
        opacity={opacity}
        animated={animated}
        className="text-zinc-100 drop-shadow-[0_0_12px_rgba(255,255,255,0.22)] transition-all duration-300 group-hover:drop-shadow-[0_0_18px_rgba(255,255,255,0.45)] group-hover:scale-105"
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}