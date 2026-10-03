// Brand mark: a faceted space sphere with a compass star and moon above it.
// Deliberately not a pentagon - the brief forbids five-sided shapes.
// Two assets: the full logo reads well from ~24px up, the sphere-only mark
// stays legible at 12-14px where the compass detail turns to noise.
const LOGO_SRC = '/pentagon-logo.png'
const MARK_SRC = '/pentagon-mark.png'

export function Logomark({ size = 18, className = '' }: { size?: number; className?: string }) {
  const src = size < 22 ? MARK_SRC : LOGO_SRC
  return (
    <img
      src={src}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      className={`shrink-0 select-none object-contain ${className}`}
    />
  )
}

export function LogomarkBadge({
  size = 34,
  className = '',
  label,
}: {
  size?: number
  className?: string
  label?: string
}) {
  return (
    <span
      className={`grid shrink-0 place-items-center overflow-hidden rounded-[12px] border border-white/[0.08] bg-white/[0.03] ${className}`}
      style={{ width: size, height: size }}
    >
      <Logomark size={Math.round(size * 0.92)} />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}