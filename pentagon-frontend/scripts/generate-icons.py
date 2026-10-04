#!/usr/bin/env python3
"""Derive every launcher icon from the brand assets in public/.

`npx cap` ships the stock Capacitor robot in the Android and iOS icon sets,
which is what the launcher shows until someone replaces it. This script is the
answer to that: it renders the real Pentagon mark into every icon slot, so the
app reads as the brand on a phone home screen as well as in the window.

Two source assets, same split the UI uses in src/components/Logomark.tsx:
  pentagon-logo.png  full logo (sphere + compass star + moon), legible ~24px up
  pentagon-mark.png  sphere-only mark, stays legible below that

Nothing here is hand-placed artwork - edit the two PNGs in public/ and re-run
`npm run icons` to propagate. Requires Pillow (pip install Pillow).

Layout rules worth knowing before you tune the fractions:

* Android adaptive icons are 108dp with only the central 66dp guaranteed
  visible, so the foreground mark is inset hard (see FOREGROUND_FRACTION).
* Android legacy icons are drawn by the launcher with no mask at all, so they
  carry their own rounded shape instead of bleeding off the tile.
* iOS rejects an alpha channel on AppIcon, so the 1024 export is flattened to
  RGB on the background colour.
"""

from __future__ import annotations

import glob
import os
import sys
import xml.dom.minidom

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
ANDROID_RES = os.path.join(ROOT, "android", "app", "src", "main", "res")
IOS_ICONSET = os.path.join(ROOT, "ios", "App", "App", "Assets.xcassets", "AppIcon.appiconset")

# Matches --surface-app in src/index.css and the theme-color meta in index.html.
BACKGROUND = (0, 0, 0, 255)

# Fraction of the tile the mark's longest side spans.
LEGACY_FRACTION = 0.66
ROUND_FRACTION = 0.66
FOREGROUND_FRACTION = 0.50
IOS_FRACTION = 0.62
FAVICON_FRACTION = 0.74
APPLE_TOUCH_FRACTION = 0.72

# density -> legacy icon edge, adaptive foreground edge (108dp canvas)
DENSITIES = {
    "mdpi": (48, 108),
    "hdpi": (72, 162),
    "xhdpi": (96, 216),
    "xxhdpi": (144, 324),
    "xxxhdpi": (192, 432),
}

# Legacy launchers draw the tile unmasked, so give it a shape of its own.
LEGACY_CORNER_RADIUS = 0.18


def _normalise_alpha(image: Image.Image) -> Image.Image:
    """Stretch a partially transparent asset to full range.

    The brand PNGs cap out around 75% alpha because they sit on a dark app
    surface at runtime. An icon has no such surface - it is composited on an
    opaque plate - so leaving the alpha alone renders the mark muddy grey.
    Rescaling the ramp (rather than flattening it) keeps the soft edges that
    give the sphere and the compass star their shape.
    """
    peak = image.getchannel("A").getextrema()[1]
    if peak == 0 or peak == 255:
        return image
    alpha = image.getchannel("A").point(lambda value: round(255 * value / peak))
    image.putalpha(alpha)
    return image


def _load(name: str) -> Image.Image:
    image = Image.open(os.path.join(PUBLIC, name)).convert("RGBA")
    return _normalise_alpha(image)


def _plate(size: int, shape: str) -> Image.Image:
    """The opaque backing the mark sits on."""
    if shape == "square":
        return Image.new("RGBA", (size, size), BACKGROUND)
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    if shape == "circle":
        draw.ellipse((0, 0, size - 1, size - 1), fill=BACKGROUND)
    elif shape == "rounded":
        draw.rounded_rectangle(
            (0, 0, size - 1, size - 1),
            radius=round(size * LEGACY_CORNER_RADIUS),
            fill=BACKGROUND,
        )
    else:
        raise ValueError(f"unknown plate shape: {shape}")
    return plate


def _place(mark: Image.Image, size: int, fraction: float) -> Image.Image:
    """Scale the mark to `fraction` of the tile and centre it."""
    longest = max(mark.size)
    target = max(1, round(size * fraction))
    scale = target / longest
    scaled = mark.resize(
        (max(1, round(mark.width * scale)), max(1, round(mark.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2)
    )
    return canvas


def _tile(size: int, mark: Image.Image, fraction: float, shape: str) -> Image.Image:
    plate = _plate(size, shape)
    plate.alpha_composite(_place(mark, size, fraction))
    return plate


def write_android() -> list[str]:
    logo, mark = _load("pentagon-logo.png"), _load("pentagon-mark.png")
    written = []
    for density, (legacy, foreground) in DENSITIES.items():
        folder = os.path.join(ANDROID_RES, f"mipmap-{density}")
        os.makedirs(folder, exist_ok=True)
        for name, image in (
            ("ic_launcher.png", _tile(legacy, logo, LEGACY_FRACTION, "rounded")),
            ("ic_launcher_round.png", _tile(legacy, logo, ROUND_FRACTION, "circle")),
            # Foreground sits under the launcher's mask: no plate, and only the
            # mark, kept inside the 66dp safe zone.
            ("ic_launcher_foreground.png", _place(mark, foreground, FOREGROUND_FRACTION)),
        ):
            path = os.path.join(folder, name)
            image.save(path, "PNG", optimize=True)
            written.append(path)
    return written


def write_ios() -> list[str]:
    # The full logo rather than the sphere-only mark: iOS renders this at 180px
    # and up, well past the point where the compass star resolves.
    icon = _tile(1024, _load("pentagon-logo.png"), IOS_FRACTION, "square")
    # App Store Connect rejects an alpha channel outright.
    opaque = Image.new("RGB", icon.size, BACKGROUND[:3])
    opaque.paste(icon, (0, 0), icon)
    os.makedirs(IOS_ICONSET, exist_ok=True)
    path = os.path.join(IOS_ICONSET, "AppIcon-512@2x.png")
    opaque.save(path, "PNG", optimize=True)
    return [path]


def write_web() -> list[str]:
    """The two icon slots the browser page and iOS home screen ask for."""
    # Under ~22px the compass star turns to noise, so the tab reuses the same
    # sphere-only mark the sidebar falls back to.
    icon = _tile(256, _load("pentagon-mark.png"), FAVICON_FRACTION, "square")
    ico = os.path.join(PUBLIC, "favicon.ico")
    icon.save(ico, "ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    # Safari composites a transparent apple-touch-icon on white, which inverts
    # a light mark on a dark plate. Ship it opaque, and the full logo fits at
    # 180px comfortably.
    touch = _tile(180, _load("pentagon-logo.png"), APPLE_TOUCH_FRACTION, "square")
    opaque = Image.new("RGB", touch.size, BACKGROUND[:3])
    opaque.paste(touch, (0, 0), touch)
    touch_path = os.path.join(PUBLIC, "apple-touch-icon.png")
    opaque.save(touch_path, "PNG", optimize=True)
    return [ico, touch_path]


def check_android_resources() -> None:
    """Fail loudly on a malformed resource file.

    The plate colour lives in res/values/ic_launcher_background.xml, so the one
    command that owns the icon set also owns the XML that points at it. Nothing
    else in the frontend toolchain reads res/, so a typo here - a `--` inside a
    comment, say, which is illegal in XML and rejected by aapt2 - would
    otherwise surface only at `gradlew assemble`, long after the edit.
    """
    for path in glob.glob(os.path.join(ANDROID_RES, "**", "*.xml"), recursive=True):
        xml.dom.minidom.parse(path)


def main() -> int:
    written = [*write_android(), *write_ios(), *write_web()]
    for path in written:
        image = Image.open(path)
        print(f"  {os.path.relpath(path, ROOT)}  {image.size[0]}x{image.size[1]} {image.mode}")
    print(f"{len(written)} icon files regenerated from public/pentagon-{{logo,mark}}.png")
    check_android_resources()
    print("android res/ XML parses clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())