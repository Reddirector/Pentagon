#!/usr/bin/env python3
"""Trace brand mark into multi-layer semantic SVG vector paths.

Produces mathematically precise, subpixel-interpolated vector curves directly
from the antialiased artwork, preserving:
  - 8-pointed celestial compass star with sharp needle rays
  - Circular orbit halo ring
  - Crescent moon and 4-pointed radiant sparkles
  - 3D polyhedral dodecahedron with beveled struts
  - Translucent glass facet panels for refractive 3D depth

Structured into animatable layers ready for CSS keyframes.
Regenerate with `npm run vectorize`.
"""

from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")

_CASES = {
    1: ((3, 0),), 2: ((0, 1),), 3: ((3, 1),), 4: ((1, 2),), 6: ((0, 2),),
    7: ((3, 2),), 8: ((2, 3),), 9: ((0, 2),), 11: ((1, 2),), 12: ((1, 3),),
    13: ((0, 1),), 14: ((0, 3),),
}


def _lerp(a: np.ndarray, b: np.ndarray, iso: float) -> np.ndarray:
    span = b - a
    safe = np.where(np.abs(span) < 1e-12, 1e-12, span)
    return (iso - a) / safe


def marching_squares(field: np.ndarray, iso: float) -> list[list[tuple[float, float]]]:
    """Closed loops bounding every region of field above iso with subpixel linear interpolation."""
    fh, fw = field.shape
    padded = np.zeros((fh + 1, fw + 1), dtype=np.float64)
    padded[:fh, :fw] = field
    inside = padded > iso
    tl, tr = inside[:fh, :fw], inside[:fh, 1 : fw + 1]
    br, bl = inside[1 : fh + 1, 1 : fw + 1], inside[1 : fh + 1, : fw]
    code = tl.astype(np.uint8) | (tr << 1) | (br << 2) | (bl << 3)
    v_tl, v_tr = padded[:fh, :fw], padded[:fh, 1 : fw + 1]
    v_br, v_bl = padded[1 : fh + 1, 1 : fw + 1], padded[1 : fh + 1, : fw]

    segments: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(list)

    def add(x: int, y: int, pair: tuple[int, int]) -> None:
        edges = []
        for edge in pair:
            if edge == 0:
                edges.append((x + _lerp(v_tl[y, x], v_tr[y, x], iso), float(y)))
            elif edge == 1:
                edges.append((float(x + 1), y + _lerp(v_tr[y, x], v_br[y, x], iso)))
            elif edge == 2:
                edges.append((x + _lerp(v_bl[y, x], v_br[y, x], iso), float(y + 1)))
            else:
                edges.append((float(x), y + _lerp(v_tl[y, x], v_bl[y, x], iso)))
        segments[(x, y)].append((edges[0], edges[1]))

    for y in range(fh):
        for x in range(fw):
            val = code[y, x]
            if val == 0 or val == 15:
                continue
            if val in _CASES:
                for pair in _CASES[val]:
                    add(x, y, pair)
            elif val == 5:
                c = field[y, x] if (x < fw and y < fh) else 0.0
                add(x, y, ((3, 0), (1, 2)) if c <= iso else ((3, 2), (0, 1)))
            elif val == 10:
                c = field[y, x] if (x < fw and y < fh) else 0.0
                add(x, y, ((0, 1), (2, 3)) if c <= iso else ((3, 0), (1, 2)))

    all_edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for s in segments.values():
        all_edges.extend(s)

    def _key(p: tuple[float, float]) -> tuple[int, int]:
        return (round(p[0] * 2048), round(p[1] * 2048))

    incident: dict[tuple[int, int], list[tuple[int, tuple[float, float]]]] = defaultdict(list)
    for idx, (st, en) in enumerate(all_edges):
        incident[_key(st)].append((idx, en))
        incident[_key(en)].append((idx, st))

    used = [False] * len(all_edges)
    loops: list[list[tuple[float, float]]] = []
    for idx, (st, en) in enumerate(all_edges):
        if used[idx]:
            continue
        used[idx] = True
        loop = [st, en]
        cur = en
        closed = False
        while True:
            hd = math.atan2(cur[1] - loop[-2][1], cur[0] - loop[-2][0])
            best, step = None, None
            for cand, other in incident[_key(cur)]:
                if used[cand] or other == loop[-2]:
                    continue
                ang = math.atan2(other[1] - cur[1], other[0] - cur[0])
                turn = abs((ang - hd + math.pi) % (2 * math.pi) - math.pi)
                if best is None or turn < best:
                    best = turn
                    step = (cand, other)
            if step is None:
                break
            used[step[0]] = True
            if step[1] == st:
                closed = True
                break
            loop.append(step[1])
            cur = step[1]
        if closed and len(loop) >= 3:
            loops.append(loop)
    return loops


def _perp(p, s, e) -> float:
    if s == e:
        return ((p[0] - s[0]) ** 2 + (p[1] - s[1]) ** 2) ** 0.5
    dx, dy = e[0] - s[0], e[1] - s[1]
    t = max(0.0, min(1.0, ((p[0] - s[0]) * dx + (p[1] - s[1]) * dy) / (dx * dx + dy * dy)))
    return ((p[0] - (s[0] + t * dx)) ** 2 + (p[1] - (s[1] + t * dy)) ** 2) ** 0.5


def douglas_peucker(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(pts) < 3:
        return list(pts)
    s, e = pts[0], pts[-1]
    idx, worst = 0, 0.0
    for i in range(1, len(pts) - 1):
        d = _perp(pts[i], s, e)
        if d > worst:
            idx, worst = i, d
    if worst <= eps:
        return [s, e]
    return douglas_peucker(pts[: idx + 1], eps)[:-1] + douglas_peucker(pts[idx:], eps)


def _signed_area(pts: list[tuple[float, float]]) -> float:
    tot = 0.0
    for i in range(len(pts) - 1):
        tot += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return tot / 2.0


def to_path(loops: list[list[tuple[float, float]]]) -> str:
    parts = []
    for l in loops:
        if len(l) < 3:
            continue
        parts.append(f"M{l[0][0]:.2f} {l[0][1]:.2f}" + "".join(f"L{x:.2f} {y:.2f}" for x, y in l[1:]) + "Z")
    return "".join(parts)


def main() -> int:
    name = "pentagon-logo.png"
    src_path = os.path.join(PUBLIC, name)
    if not os.path.exists(src_path):
        print(f"Error: {src_path} not found", file=sys.stderr)
        return 1

    img = Image.open(src_path).convert("RGBA")
    arr = np.asarray(img, dtype=np.float64)
    alpha = arr[..., 3] / 255.0

    pad = 8
    h, w = alpha.shape
    p_alpha = np.zeros((h + 2 * pad, w + 2 * pad), dtype=np.float64)
    p_alpha[pad : pad + h, pad : pad + w] = alpha

    # 1. Crown loops (y < 120): threshold 0.16 captures fine star rays and halo
    crown_field = p_alpha.copy()
    crown_field[120:, :] = 0
    crown_raw = marching_squares(crown_field, 0.16)
    crown_simp = [douglas_peucker(l, 0.25) for l in crown_raw if len(l) >= 3]

    cx, cy = 247 + pad, 71 + pad
    orbit_loops, moon_loops, sparkle_loops, star_loops = [], [], [], []
    for l in crown_simp:
        mx = sum(p[0] for p in l) / len(l)
        my = sum(p[1] for p in l) / len(l)
        r = np.hypot(mx - cx, my - cy)
        area = abs(_signed_area(l))
        if 280 < mx < 315 and 15 < my < 45 and area > 12:
            moon_loops.append(l)
        elif area < 15:
            sparkle_loops.append(l)
        elif 40 < r < 56 and area < 90 and not (abs(mx - cx) < 18 or abs(my - cy) < 18):
            orbit_loops.append(l)
        else:
            star_loops.append(l)

    # 2. Globe struts (y >= 118): threshold 0.26 captures structural wireframe
    globe_field = p_alpha.copy()
    globe_field[:118, :] = 0
    struts_raw = marching_squares(globe_field, 0.26)
    struts_simp = [douglas_peucker(l, 0.30) for l in struts_raw if len(l) >= 3]

    # 3. Facets (y >= 118): threshold 0.14 captures glass translucency
    facets_field = p_alpha.copy()
    facets_field[:118, :] = 0
    facets_raw = marching_squares(facets_field, 0.14)
    facets_simp = [douglas_peucker(l, 0.50) for l in facets_raw if len(l) >= 3]

    star_path = to_path(star_loops)
    orbit_path = to_path(orbit_loops)
    moon_path = to_path(moon_loops)
    sparkles_path = to_path(sparkle_loops)
    struts_path = to_path(struts_simp)
    facets_path = to_path(facets_simp)
    crown_path = to_path(crown_simp)
    globe_path = struts_path

    viewbox = f"0 0 {w + 2 * pad} {h + 2 * pad}"

    ts_content = f"""// GENERATED FILE - do not edit by hand.
// Produced by `npm run vectorize` (scripts/vectorize-logo.py) from
// public/pentagon-logo.png with subpixel antialiased contour tracing.
//
// The logo is a pure mathematical SVG vector mark, structured into semantic
// animatable layers:
//   - LOGO_STAR_PATH: Faceted 8-pointed celestial compass star
//   - LOGO_ORBIT_PATH: Circular orbital halo ring around the compass
//   - LOGO_MOON_PATH: Crescent moon in the upper constellation
//   - LOGO_SPARKLES_PATH: 4-pointed starlets and radiant sparkles
//   - LOGO_STRUTS_PATH: 3D beveled dodecahedral crystal struts
//   - LOGO_FACETS_PATH: Translucent glass facet panels with refractive depth

export const LOGO_VIEWBOX = '{viewbox}'

export const LOGO_STAR_PATH =
  '{star_path}'

export const LOGO_ORBIT_PATH =
  '{orbit_path}'

export const LOGO_MOON_PATH =
  '{moon_path}'

export const LOGO_SPARKLES_PATH =
  '{sparkles_path}'

export const LOGO_CROWN_PATH =
  '{crown_path}'

export const LOGO_STRUTS_PATH =
  '{struts_path}'

export const LOGO_FACETS_PATH =
  '{facets_path}'

export const LOGO_GLOBE_PATH =
  '{globe_path}'

export const LOGO_PATH =
  '{crown_path}{struts_path}'
"""

    target_ts = os.path.join(ROOT, "src", "components", "logoPaths.ts")
    with open(target_ts, "w", encoding="utf-8") as f:
        f.write(ts_content)

    print(f"Generated {target_ts}")
    print(f"  Crown: {len(crown_simp)} loops ({len(star_loops)} star, {len(orbit_loops)} orbit, {len(moon_loops)} moon, {len(sparkle_loops)} sparkles)")
    print(f"  Globe: {len(struts_simp)} strut loops, {len(facets_simp)} facet loops")
    return 0


if __name__ == "__main__":
    sys.exit(main())