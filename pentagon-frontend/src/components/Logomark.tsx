// Orbit mark: a thin ring with one small filled dot resting on the ring.
// Deliberately not a pentagon — the brief forbids five-sided shapes.
export function Logomark({ size = 18, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 200 200"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <circle cx="100" cy="100" r="66" stroke="currentColor" strokeWidth="7" opacity=".62" />
      <circle cx="166" cy="100" r="13" fill="currentColor" />
    </svg>
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
      className={`grid shrink-0 place-items-center rounded-[12px] bg-emerald-300 text-[#142017] shadow-[0_0_0_1px_rgba(110,231,183,.28),0_6px_18px_rgba(110,231,183,.14)] ${className}`}
      style={{ width: size, height: size }}
    >
      <Logomark size={Math.round(size * 0.56)} />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}