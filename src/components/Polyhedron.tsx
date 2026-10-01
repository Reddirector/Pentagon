import { cn } from "@/lib/utils";

/**
 * Wireframe icosahedron (20-face polyhedron) rendered as an SVG.
 * A stylized "Pentagon" mark: glowing white/violet wireframe with
 * optional orbiting rings, like the reference dashboard hero.
 */
export function Polyhedron({
  className,
  size = 96,
  glow = true,
  orbits = false,
  caption,
}: {
  className?: string;
  size?: number;
  glow?: boolean;
  orbits?: boolean;
  caption?: string;
}) {
  return (
    <div
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      {orbits && (
        <>
          <div className="ptg-orbit absolute inset-[-22%] rounded-full border border-foreground/10" />
          <div className="ptg-orbit-reverse absolute inset-[-40%] rounded-full border border-foreground/[0.07]" />
          <div
            className="ptg-orbit absolute inset-[-8%] rounded-full border border-dashed border-primary/20"
            style={{ animationDuration: "90s" }}
          />
        </>
      )}

      {glow && (
        <div className="ptg-glow absolute inset-[18%] rounded-full bg-primary/30 blur-2xl" />
      )}

      <svg
        viewBox="0 0 100 100"
        width={size}
        height={size}
        className="relative"
        aria-hidden="true"
        fill="none"
      >
        <defs>
          <linearGradient id="ptg-edge" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#c4b5fd" stopOpacity="0.85" />
          </linearGradient>
        </defs>

        {/* outer silhouette */}
        <polygon
          points="50,3 89,25 89,71 50,97 11,71 11,25"
          stroke="url(#ptg-edge)"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        {/* hexagonal belt */}
        <polygon
          points="50,15 78,31 78,65 50,85 22,65 22,31"
          stroke="#ffffff"
          strokeOpacity="0.5"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        {/* upper cap pentagon */}
        <polygon
          points="50,3 68,20 61,40 39,40 32,20"
          stroke="#ffffff"
          strokeOpacity="0.55"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        {/* lower cap pentagon */}
        <polygon
          points="50,97 68,80 61,60 39,60 32,80"
          stroke="#ffffff"
          strokeOpacity="0.55"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        {/* spokes: top apex -> belt, bottom apex -> belt */}
        <g stroke="#ffffff" strokeOpacity="0.38" strokeWidth="0.9">
          <line x1="50" y1="3" x2="50" y2="15" />
          <line x1="89" y1="25" x2="78" y2="31" />
          <line x1="89" y1="71" x2="78" y2="65" />
          <line x1="50" y1="97" x2="50" y2="85" />
          <line x1="11" y1="25" x2="22" y2="31" />
          <line x1="11" y1="71" x2="22" y2="65" />
          {/* belt triangulation */}
          <line x1="50" y1="15" x2="39" y2="40" />
          <line x1="50" y1="15" x2="61" y2="40" />
          <line x1="22" y1="31" x2="39" y2="40" />
          <line x1="78" y1="31" x2="61" y2="40" />
          <line x1="22" y1="31" x2="39" y2="60" />
          <line x1="22" y1="65" x2="39" y2="60" />
          <line x1="78" y1="31" x2="61" y2="60" />
          <line x1="78" y1="65" x2="61" y2="60" />
          <line x1="50" y1="85" x2="39" y2="60" />
          <line x1="50" y1="85" x2="61" y2="60" />
        </g>
        {/* vertices */}
        <g fill="#ffffff">
          {[
            [50, 3],
            [89, 25],
            [89, 71],
            [50, 97],
            [11, 25],
            [11, 71],
            [50, 15],
            [78, 31],
            [78, 65],
            [50, 85],
            [22, 31],
            [22, 65],
            [39, 40],
            [61, 40],
            [39, 60],
            [61, 60],
          ].map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="1.4" fillOpacity="0.85" />
          ))}
        </g>
      </svg>

      {caption && (
        <p
          className="absolute -bottom-2 left-1/2 -translate-x-1/2 whitespace-nowrap text-[9px] font-semibold uppercase tracking-[0.3em] text-muted-foreground"
          style={{ fontSize: Math.max(7, size / 14) }}
        >
          {caption}
        </p>
      )}
    </div>
  );
}

export default Polyhedron;
