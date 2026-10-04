#!/usr/bin/env python3
"""Trace the brand PNGs into SVG path data.

The in-app mark used to be an <img> pointing at a PNG, which made the browser
treat the logo as a picture: Chrome will start a native image drag from it, so
dragging the logo into the composer puts a drag ghost (and, on some paths, the
image itself) into the message. An inline <svg> root has no such affordance, so
vectorising removes the bug rather than papering over it with draggable=false.

The mark is a wireframe globe: dozens of strokes that cross each other. Tracing
it in one pass is not enough - marching squares emits one closed loop per stroke
edge, and filling those with evenodd punches a hole wherever two strokes cross.
So this runs twice:

  1. trace the antialiased artwork into stroke contours,
  2. rasterise their union into a binary mask,
  3. trace the mask boundary again.

The second pass is what makes fill-rule=evenodd correct. Marching squares never
reverses its traversal at a hole - a one-pixel blob and a one-pixel hole in the
same cell emit the same segment direction - so classifying loops as solid or
hollow by winding is a losing game. But once the strokes have been rasterised
into a union mask, the surviving loops are only ever disjoint or nested: two
strokes that cross have already merged into one region. Even-odd parity is
exactly right for that, and it needs no orientation bookkeeping at all.

`npm run vectorize` regenerates src/components/logoPaths.ts. Requires Pillow and
numpy. See the neighbouring generate-icons.py, which rasterises the result.

Only the full logo is emitted. pentagon-mark.png is the sphere-only variant that
Logomark used below 22px, because a 256px *raster* loses the compass detail when
the browser scales it to 16px. As a vector the single logo stays sharp at every
size, so a second path would be duplicated geometry for a distinction the
renderer no longer needs; tracing it also measured worse (IoU 0.54 against 0.81),
since the 1-2px gaps between facets do not survive contour simplification.
"""

from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

import numpy as np
from PIL import Image, ImageChops, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")

# Where the perceived-ink crosses this, the stroke boundary. The artwork peaks
# near 0.48 on the app's black surface, so this keeps the soft stroke edges and
# trims only the sensor noise.
ISO = 0.055

# Douglas-Peucker tolerance in source pixels. Measured against the rasterised
# source: 0.5 holds IoU ~0.81 on the logo while keeping the path to roughly a
# fifth of the PNG's bytes. Tightening past 0.3 buys nothing visible and triples
# the file.
SIMPLIFY = 0.5

# Clear margin added around each asset before tracing, as a fraction of its
# shorter side. The mark's ink reaches its own edge; tracing it flush breaks the
# contour walk. See padded_ink.
PAD_FRACTION = 0.015

# Corner cutting rounds off marching squares' 1px staircase, but on strokes this
# thick it also fattens them and closes the gaps between neighbouring facets.
# Measured, it cost ~0.01 IoU and a third of the path size to switch it off.
CHAIKIN_ROUNDS = 0


def load_ink(name: str) -> np.ndarray:
    """Perceived ink of the artwork as it actually appears on the app surface.

    Multiplying luminance by alpha is not just convenient, it matters: the PNGs
    cap out around 75% alpha because they were drawn to sit on a dark backdrop,
    and a threshold on raw alpha alone would trace the wrong silhouette.
    """
    image = Image.open(os.path.join(PUBLIC, name)).convert("RGBA")
    pixels = np.asarray(image, dtype=np.float64)
    alpha = pixels[..., 3] / 255.0
    luminance = (pixels[..., :3] @ np.array([0.299, 0.587, 0.114])) / 255.0
    return alpha * luminance


# --------------------------------------------------------------------------
# Marching squares
# --------------------------------------------------------------------------

# Corners are numbered TL=1 TR=2 BR=4 BL=8, edges top=0 right=1 bottom=2 left=3.
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
    """Closed loops bounding every region of `field` above `iso`."""
    h, w = field.shape
    padded = np.zeros((h + 1, w + 1), dtype=np.float64)
    padded[:h, :w] = field
    inside = padded > iso

    tl, tr = inside[:h, :w], inside[:h, 1 : w + 1]
    br, bl = inside[1 : h + 1, 1 : w + 1], inside[1 : h + 1, : w]
    code = tl.astype(np.uint8) | (tr << 1) | (br << 2) | (bl << 3)

    v_tl, v_tr = padded[:h, :w], padded[:h, 1 : w + 1]
    v_br, v_bl = padded[1 : h + 1, 1 : w + 1], padded[1 : h + 1, : w]

    segments: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(list)

    def add(x: int, y: int, pair: tuple[int, int]) -> None:
        edges = []
        for edge in pair:
            if edge == 0:      # top: TL -> TR
                edges.append((x + _lerp(v_tl[y, x], v_tr[y, x], iso), float(y)))
            elif edge == 1:    # right: TR -> BR
                edges.append((float(x + 1), y + _lerp(v_tr[y, x], v_br[y, x], iso)))
            elif edge == 2:    # bottom: BL -> BR
                edges.append((x + _lerp(v_bl[y, x], v_br[y, x], iso), float(y + 1)))
            else:              # left: TL -> BL
                edges.append((float(x), y + _lerp(v_tl[y, x], v_bl[y, x], iso)))
        segments[(x, y)].append((edges[0], edges[1]))

    for y in range(h):
        for x in range(w):
            value = code[y, x]
            if value == 0 or value == 15:
                continue
            if value in _CASES:
                for pair in _CASES[value]:
                    add(x, y, pair)
            elif value == 5:
                # Saddle: which corners belong together is decided by the cell
                # centre, the one thing the corners alone cannot say.
                centre = field[y, x] if (x < w and y < h) else 0.0
                add(x, y, ((3, 0), (1, 2)) if centre <= iso else ((3, 2), (0, 1)))
            elif value == 10:
                centre = field[y, x] if (x < w and y < h) else 0.0
                add(x, y, ((0, 1), (2, 3)) if centre <= iso else ((3, 0), (1, 2)))

    return _chain(segments)


def _key(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] * 2048), round(point[1] * 2048))


def _chain(segments: dict) -> list[list[tuple[float, float]]]:
    """Walk loose segments into closed loops by matching shared endpoints."""
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for cell_segments in segments.values():
        edges.extend(cell_segments)

    incident: dict[tuple[int, int], list[tuple[int, tuple[float, float]]]] = defaultdict(list)
    for index, (start, end) in enumerate(edges):
        incident[_key(start)].append((index, end))
        incident[_key(end)].append((index, start))

    used = [False] * len(edges)
    loops: list[list[tuple[float, float]]] = []
    for index, (start, end) in enumerate(edges):
        if used[index]:
            continue
        used[index] = True
        loop = [start, end]
        current = end
        closed = False
        while True:
            heading = math.atan2(current[1] - loop[-2][1], current[0] - loop[-2][0])
            step = None
            best = None
            for candidate, other in incident[_key(current)]:
                if used[candidate] or other == loop[-2]:
                    continue
                # At a junction - a stroke self-touching, or a saddle - more
                # than one segment leaves this point. Taking them in dict order
                # splices unrelated branches into one loop, which renders as a
                # bowtie that fills the wrong region entirely. Continuing with
                # the straightest candidate keeps each contour on its own
                # stroke, which is what the eye reads as the boundary.
                angle = math.atan2(other[1] - current[1], other[0] - current[0])
                turn = abs((angle - heading + math.pi) % (2 * math.pi) - math.pi)
                if best is None or turn < best:
                    best = turn
                    step = (candidate, other)
            if step is None:
                break  # ran off the end of an open chain
            used[step[0]] = True
            if step[1] == start:
                closed = True
                break
            loop.append(step[1])
            current = step[1]
        # An unclosed chain is dropped rather than emitted as an open subpath,
        # which nonzero fill would bleed across the shape.
        if closed and len(loop) >= 3:
            loops.append(loop)
    return loops


# --------------------------------------------------------------------------
# Simplification and smoothing
# --------------------------------------------------------------------------


def _perpendicular_distance(point, start, end) -> float:
    if start == end:
        return ((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2) ** 0.5
    dx, dy = end[0] - start[0], end[1] - start[1]
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px, py = start[0] + t * dx, start[1] + t * dy
    return ((point[0] - px) ** 2 + (point[1] - py) ** 2) ** 0.5


def douglas_peucker(points, epsilon):
    if len(points) < 3:
        return list(points)
    start, end = points[0], points[-1]
    index, worst = 0, 0.0
    for i in range(1, len(points) - 1):
        distance = _perpendicular_distance(points[i], start, end)
        if distance > worst:
            index, worst = i, distance
    if worst <= epsilon:
        return [start, end]
    return douglas_peucker(points[: index + 1], epsilon)[:-1] + douglas_peucker(points[index:], epsilon)


def chaikin(points, rounds=CHAIKIN_ROUNDS):
    """Corner cutting. Marching squares leaves 1px staircases; this removes them
    without the overshoot a spline fit would put on the facet corners."""
    for _ in range(rounds):
        if len(points) < 4:
            break
        out = [points[0]]
        for i in range(len(points) - 1):
            ax, ay = points[i]
            bx, by = points[i + 1]
            out.append((ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25))
            out.append((ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75))
        out.append(points[-1])
        points = out
    return points


def _signed_area(points) -> float:
    total = 0.0
    for i in range(len(points) - 1):
        total += points[i][0] * points[i + 1][1] - points[i + 1][0] * points[i][1]
    return total / 2.0


def _polarity_unused():
    """Removed: see the module docstring on why evenodd replaces this."""


def padded_ink(name: str) -> tuple[np.ndarray, int]:
    """Ink on a canvas with a clear margin all round.

    pentagon-mark.png has ink that runs off its own edge. Marching squares then
    closes contours along the canvas border and the chainer loses them: the
    traced mark came out at 47% agreement with the original, and 82% once there
    was somewhere for the contour to go. Both assets are padded by the same
    fraction so they keep their relative weight.
    """
    ink = load_ink(name)
    height, width = ink.shape
    pad = max(2, round(min(height, width) * PAD_FRACTION))
    padded = np.zeros((height + 2 * pad, width + 2 * pad), dtype=np.float64)
    padded[pad : pad + height, pad : pad + width] = ink
    return padded, pad


def _polygon_mask(loops, size) -> Image.Image:
    """Even-odd composite of every loop, exactly as the SVG fill will render it.

    Plain union is wrong here: the tracer emits a loop for the inside of a hole
    as well as for its rim, so union-filling fills the hole back in and an
    annulus silently becomes a disc. Parity - which is XOR - is what the final
    fill-rule=evenodd does, so computing it here keeps the two in step.
    """
    accumulator = Image.new("1", size, 0)
    for loop in loops:
        mask = Image.new("1", size, 0)
        ImageDraw.Draw(mask).polygon([(float(x), float(y)) for x, y in loop], fill=1)
        accumulator = ImageChops.logical_xor(accumulator, mask)
    return accumulator


def vectorize(ink: np.ndarray):
    """Two-pass trace: artwork -> stroke contours -> union -> boundary loops."""
    height, width = ink.shape
    stroke_loops = marching_squares(ink, ISO)
    if not stroke_loops:
        raise SystemExit("no contours found - check ISO against the artwork")

    union = np.asarray(_polygon_mask(stroke_loops, (width, height)), dtype=np.float64)
    boundary = marching_squares(union, 0.5)

    prepared = []
    for loop in boundary:
        if len(loop) < 3:
            continue
        simplified = douglas_peucker(loop, SIMPLIFY)
        if len(simplified) < 3:
            continue
        smoothed = chaikin(simplified)
        if abs(_signed_area(smoothed)) < 1.0:
            continue
        prepared.append(smoothed)

    return prepared, len(stroke_loops), len(boundary)


def to_path(loops) -> str:
    parts = []
    for loop in loops:
        if len(loop) < 3:
            continue
        head = loop[0]
        parts.append(f"M{head[0]:.2f} {head[1]:.2f}" + "".join(f"L{x:.2f} {y:.2f}" for x, y in loop[1:]) + "Z")
    return "".join(parts)


def main() -> int:
    name = "pentagon-logo.png"
    ink, pad = padded_ink(name)
    loops, strokes, boundaries = vectorize(ink)
    path = to_path(loops)
    points = sum(len(loop) for loop in loops)
    height, width = ink.shape
    print(
        f"  {name}: {strokes} stroke loops -> {boundaries} boundary loops, "
        f"{points} points, {len(path)} bytes of path, {width}x{height} viewBox "
        f"(+{pad}px margin)"
    )
    if not path:
        print("no path produced - check ISO against the artwork", file=sys.stderr)
        return 1

    logo_box = f"0 0 {width} {height}"
    module = f'''// GENERATED FILE - do not edit by hand.
// Produced by `npm run vectorize` (scripts/vectorize-logo.py) from
// public/pentagon-logo.png.
//
// The logo used to be an <img> pointing at those PNGs. Browsers treat an <img>
// as a picture and will happily start a native image drag from it, so the mark
// could be dragged into the composer and dropped as a message attachment. An
// inline <svg> has no such affordance, and scaling cleanly is the reason the
// raster was dropped rather than the drag suppressed.
//
// fill-rule is evenodd, and it is only correct because of how this path was
// built: the strokes were rasterised into a union mask first, so the loops below
// are disjoint or nested and never merely overlapping. Tracing the strokes
// directly would make evenodd punch a hole at every crossing.

export const LOGO_VIEWBOX = '{logo_box}'
export const LOGO_PATH =
  '{path}'
'''
    target = os.path.join(ROOT, "src", "components", "logoPaths.ts")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(module)
    print(f"wrote {os.path.relpath(target, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())