import { LOGO_VIEWBOX, LOGO_CROWN_PATH, LOGO_GLOBE_PATH } from './logoPaths'

/**
 * Pentagon Brand Mark: Pure Mathematical SVG Vector.
 * Vectorized with subpixel precision from the official Pentagon brand mark.
 * Structurally split into celestial crown (star, moon, orbit) and faceted
 * dodecahedral space globe for smooth CSS animations and crisp rendering at any size.
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
      <g className={animated ? 'logo-crown' : ''}>
        <path
          d={LOGO_CROWN_PATH}
          fill="currentColor"
          fillRule="evenodd"
          opacity={0.95}
        />
      </g>
      <g className={animated ? 'logo-globe' : ''}>
        <path
          d={LOGO_GLOBE_PATH}
          fill="currentColor"
          fillRule="evenodd"
          opacity={0.9}
        />
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
        className="text-emerald-400 drop-shadow-[0_0_12px_rgba(52,211,153,0.38)] transition-all duration-300 group-hover:drop-shadow-[0_0_18px_rgba(52,211,153,0.65)] group-hover:scale-105"
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}