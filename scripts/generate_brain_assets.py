#!/usr/bin/env python3
"""Generate Pentagon Brain animation assets:
- docs/assets/pentagon-brain-animated.svg (Pure vector, infinite CSS keyframe animation)
- docs/assets/pentagon-brain-animated.gif (High-FPS 60-frame perfectly looping GIF)
- docs/assets/pentagon-brain.png (High-res 800x800 hero still image)
- docs/assets/brain-animation.html (Standalone interactive demo web page)
Also mirrors these assets to pentagon-frontend/public/ for direct Vercel serving.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_ASSETS = os.path.join(ROOT, "docs", "assets")
PUBLIC = os.path.join(ROOT, "pentagon-frontend", "public")
LOGO_PATHS_FILE = os.path.join(ROOT, "pentagon-frontend", "src", "components", "logoPaths.ts")

os.makedirs(DOCS_ASSETS, exist_ok=True)
os.makedirs(PUBLIC, exist_ok=True)


def load_logo_paths() -> dict[str, str]:
    with open(LOGO_PATHS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    def get_const(name: str) -> str:
        m = re.search(r"export const " + name + r"\s*=\s*['\"]([^'\"]+)['\"]", content)
        return m.group(1) if m else ""

    return {
        "viewbox": get_const("LOGO_VIEWBOX") or "0 0 528 528",
        "star": get_const("LOGO_STAR_PATH"),
        "orbit": get_const("LOGO_ORBIT_PATH"),
        "moon": get_const("LOGO_MOON_PATH"),
        "sparkles": get_const("LOGO_SPARKLES_PATH"),
        "struts": get_const("LOGO_STRUTS_PATH"),
        "facets": get_const("LOGO_FACETS_PATH"),
    }


def generate_standalone_animated_svg(paths: dict[str, str], output_path: str) -> None:
    """Creates a standalone, self-animating SVG vector file with embedded CSS keyframes."""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 528 528" width="100%" height="100%" role="img" aria-label="Pentagon AI Brain Mark">
  <defs>
    <radialGradient id="card-bg" cx="50%" cy="38%" r="65%">
      <stop offset="0%" stop-color="#0f192b" />
      <stop offset="65%" stop-color="#06090e" />
      <stop offset="100%" stop-color="#020407" />
    </radialGradient>
    <radialGradient id="halo-glow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#34d399" stop-opacity="0.55" />
      <stop offset="50%" stop-color="#10b981" stop-opacity="0.22" />
      <stop offset="100%" stop-color="#059669" stop-opacity="0" />
    </radialGradient>
    <linearGradient id="glass-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#6ee7b7" stop-opacity="0.45" />
      <stop offset="45%" stop-color="#10b981" stop-opacity="0.25" />
      <stop offset="100%" stop-color="#047857" stop-opacity="0.08" />
    </linearGradient>
    <linearGradient id="struts-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" />
      <stop offset="40%" stop-color="#a7f3d0" />
      <stop offset="100%" stop-color="#34d399" />
    </linearGradient>
    <filter id="glow-bright" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3.5" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  </defs>

  <style>
    @keyframes spin-cw {{
      from {{ transform: rotate(0deg); }}
      to {{ transform: rotate(360deg); }}
    }}
    @keyframes spin-ccw {{
      from {{ transform: rotate(0deg); }}
      to {{ transform: rotate(-360deg); }}
    }}
    @keyframes crown-float {{
      0%, 100% {{ transform: translateY(0px); }}
      50% {{ transform: translateY(-4px) scale(1.02); }}
    }}
    @keyframes star-pulse {{
      0%, 100% {{ transform: scale(1); opacity: 0.92; }}
      50% {{ transform: scale(1.06); opacity: 1; filter: drop-shadow(0 0 8px rgba(255,255,255,0.85)); }}
    }}
    @keyframes globe-breathe {{
      0%, 100% {{ transform: scale(1); }}
      50% {{ transform: scale(1.012); filter: drop-shadow(0 0 24px rgba(52,211,153,0.4)); }}
    }}
    @keyframes sparkle-twinkle {{
      0%, 100% {{ opacity: 0.55; transform: scale(0.94); }}
      50% {{ opacity: 1; transform: scale(1.15); }}
    }}

    .anim-outer-orbit {{
      transform-origin: 264px 264px;
      animation: spin-ccw 32s linear infinite;
    }}
    .anim-inner-halo {{
      transform-origin: 255px 79px;
      animation: spin-cw 12s linear infinite;
    }}
    .anim-crown {{
      transform-origin: 255px 79px;
      animation: crown-float 4.5s ease-in-out infinite;
    }}
    .anim-star {{
      transform-origin: 255px 79px;
      animation: star-pulse 3.2s ease-in-out infinite;
    }}
    .anim-globe {{
      transform-origin: 264px 300px;
      animation: globe-breathe 4.5s ease-in-out infinite;
    }}
    .anim-sparkles {{
      transform-origin: 255px 79px;
      animation: sparkle-twinkle 2.4s ease-in-out infinite;
    }}
  </style>

  <!-- Background rounded card -->
  <rect x="8" y="8" width="512" height="512" rx="48" fill="url(#card-bg)" stroke="#10b981" stroke-width="1.2" stroke-opacity="0.24" />

  <!-- Outer constellation orbital rings -->
  <circle cx="264" cy="264" r="236" fill="none" stroke="#ffffff" stroke-width="0.8" stroke-opacity="0.08" />
  <circle class="anim-outer-orbit" cx="264" cy="264" r="218" fill="none" stroke="#34d399" stroke-width="1.4" stroke-dasharray="14 10 24 8" stroke-opacity="0.32" />

  <!-- Background sparkle points -->
  <circle cx="68" cy="94" r="1.5" fill="#a7f3d0" opacity="0.6" />
  <circle cx="450" cy="110" r="1.8" fill="#ffffff" opacity="0.8" />
  <circle cx="460" cy="420" r="1.6" fill="#34d399" opacity="0.7" />
  <circle cx="78" cy="430" r="1.4" fill="#a7f3d0" opacity="0.6" />
  <circle cx="264" cy="38" r="1.2" fill="#ffffff" opacity="0.75" />

  <!-- 3D Polyhedral Globe (AI Brain Core) -->
  <g class="anim-globe" filter="url(#glow-bright)">
    <!-- Glass facets -->
    <path d="{paths['facets']}" fill="url(#glass-gradient)" fill-rule="evenodd" />
    <!-- Struts & bevels -->
    <path d="{paths['struts']}" fill="url(#struts-gradient)" fill-rule="evenodd" opacity="0.88" />
  </g>

  <!-- Celestial Crown -->
  <g class="anim-crown">
    <!-- Stationary outer halo ring centered at (255, 79) -->
    <circle cx="255" cy="79" r="54" fill="none" stroke="#a7f3d0" stroke-width="1.4" stroke-opacity="0.35" />

    <!-- Radiant aura glow -->
    <circle cx="255" cy="79" r="58" fill="url(#halo-glow)" />

    <!-- Rotating inner halo ring -->
    <g class="anim-inner-halo">
      <circle cx="255" cy="79" r="46.5" fill="none" stroke="#34d399" stroke-width="2" stroke-opacity="0.9" stroke-dasharray="28 8 14 6" />
      <path d="{paths['orbit']}" fill="#6ee7b7" fill-rule="evenodd" opacity="0.85" />
    </g>

    <!-- Crescent Moon -->
    <path d="{paths['moon']}" fill="#a7f3d0" fill-rule="evenodd" opacity="0.9" />

    <!-- Radiant sparkles -->
    <g class="anim-sparkles">
      <path d="{paths['sparkles']}" fill="#ffffff" fill-rule="evenodd" opacity="0.95" />
    </g>

    <!-- Compass Star -->
    <g class="anim-star">
      <path d="{paths['star']}" fill="#ffffff" fill-rule="evenodd" opacity="0.95" />
    </g>
  </g>
</svg>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Wrote animated SVG to {output_path}")


def render_html_frame(paths: dict[str, str], t: float) -> str:
    """Render HTML for frame at normalized time t in [0, 1]."""
    # Rotations
    orbit_deg = t * 360.0
    outer_orbit_deg = -t * 360.0
    # Breathing & floating
    float_y = -3.2 * math.sin(2.0 * math.pi * t)
    pulse_scale = 1.0 + 0.05 * math.sin(2.0 * math.pi * t)
    globe_scale = 1.0 + 0.012 * math.sin(2.0 * math.pi * t)
    sparkle_scale = 1.0 + 0.18 * math.sin(4.0 * math.pi * t)
    sparkle_opacity = 0.65 + 0.35 * (0.5 + 0.5 * math.sin(4.0 * math.pi * t))
    glow_opacity = 0.45 + 0.25 * (0.5 + 0.5 * math.sin(2.0 * math.pi * t))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #06080d;
    width: 480px;
    height: 480px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }}
  .card {{
    position: relative;
    width: 460px;
    height: 460px;
    border-radius: 40px;
    background: radial-gradient(circle at 50% 36%, #0f1a2c 0%, #06090f 68%, #030508 100%);
    border: 1px solid rgba(52, 211, 153, 0.22);
    box-shadow: 0 0 50px rgba(5, 150, 105, 0.18), inset 0 0 30px rgba(16, 185, 129, 0.06);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }}
  .ring-outer {{
    position: absolute;
    width: 420px;
    height: 420px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.08);
    pointer-events: none;
  }}
  .ring-orbit {{
    position: absolute;
    width: 396px;
    height: 396px;
    border-radius: 50%;
    border: 1.5px dashed rgba(52, 211, 153, 0.32);
    pointer-events: none;
    transform: rotate({outer_orbit_deg:.2f}deg);
  }}
  .star-bg {{
    position: absolute;
    border-radius: 50%;
    background: #a7f3d0;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="ring-outer"></div>
    <div class="ring-orbit"></div>

    <!-- Cosmic star particles -->
    <div class="star-bg" style="width:3px;height:3px;top:80px;left:70px;opacity:0.75;"></div>
    <div class="star-bg" style="width:2.5px;height:2.5px;top:95px;right:75px;opacity:0.85;"></div>
    <div class="star-bg" style="width:3px;height:3px;bottom:80px;right:80px;opacity:0.7;"></div>
    <div class="star-bg" style="width:2.5px;height:2.5px;bottom:90px;left:75px;opacity:0.65;"></div>
    
    <svg viewBox="{paths['viewbox']}" width="392" height="392" style="filter: drop-shadow(0 0 20px rgba(16, 185, 129, 0.35));">
      <defs>
        <radialGradient id="halo-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#34d399" stop-opacity="{glow_opacity:.2f}" />
          <stop offset="55%" stop-color="#10b981" stop-opacity="{glow_opacity * 0.4:.2f}" />
          <stop offset="100%" stop-color="#059669" stop-opacity="0" />
        </radialGradient>
        <linearGradient id="glass-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#6ee7b7" stop-opacity="0.45" />
          <stop offset="42%" stop-color="#10b981" stop-opacity="0.24" />
          <stop offset="100%" stop-color="#047857" stop-opacity="0.08" />
        </linearGradient>
        <linearGradient id="struts-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#ffffff" />
          <stop offset="45%" stop-color="#a7f3d0" />
          <stop offset="100%" stop-color="#34d399" />
        </linearGradient>
      </defs>

      <!-- Glass facets (AI Brain Dodecahedron) -->
      <g style="transform-origin: 264px 300px; transform: scale({globe_scale:.4f});">
        <path d="{paths['facets']}" fill="url(#glass-gradient)" fill-rule="evenodd" />
        <!-- Struts & bevels -->
        <path d="{paths['struts']}" fill="url(#struts-gradient)" fill-rule="evenodd" opacity="0.88" />
      </g>

      <!-- Celestial Crown (Floating Aura, Star, Rotating Halo) -->
      <g style="transform-origin: 255px 79px; transform: translateY({float_y:.2f}px);">
        <!-- Stationary outer halo ring centered at (255, 79) -->
        <circle cx="255" cy="79" r="54" fill="none" stroke="#a7f3d0" stroke-width="1.4" stroke-opacity="0.35" />

        <!-- Aura glow -->
        <circle cx="255" cy="79" r="58" fill="url(#halo-glow)" />

        <!-- Inner rotating orbit ring centered at (255, 79) -->
        <g style="transform-origin: 255px 79px; transform: rotate({orbit_deg:.2f}deg);">
          <circle cx="255" cy="79" r="46.5" fill="none" stroke="#34d399" stroke-width="1.9" stroke-opacity="0.9" stroke-dasharray="28 8 14 6" />
          <path d="{paths['orbit']}" fill="#6ee7b7" fill-rule="evenodd" opacity="0.88" />
        </g>

        <!-- Crescent moon -->
        <path d="{paths['moon']}" fill="#a7f3d0" fill-rule="evenodd" opacity="0.9" />

        <!-- Sparkles -->
        <g style="transform-origin: 255px 79px; transform: scale({sparkle_scale:.3f}); opacity: {sparkle_opacity:.2f};">
          <path d="{paths['sparkles']}" fill="#ffffff" fill-rule="evenodd" />
        </g>

        <!-- Compass Star -->
        <g style="transform-origin: 255px 79px; transform: scale({pulse_scale:.3f});">
          <path d="{paths['star']}" fill="#ffffff" fill-rule="evenodd" opacity="0.96" style="filter: drop-shadow(0 0 6px rgba(255,255,255,0.7));" />
        </g>
      </g>
    </svg>
  </div>
</body>
</html>"""


def generate_interactive_html(paths: dict[str, str], output_path: str) -> None:
    """Creates a standalone interactive demo web page with real-time controls."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pentagon — Autonomous Multimodal AI Brain</title>
  <link rel="icon" type="image/png" href="pentagon-mark.png">
  <style>
    :root {{
      --primary: #34d399;
      --primary-glow: rgba(52, 211, 153, 0.45);
      --bg-void: #06080d;
      --card-bg: radial-gradient(circle at 50% 36%, #0f192b 0%, #06090e 68%, #030508 100%);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg-void);
      color: #f3f4f6;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px;
      overflow-x: hidden;
    }}
    .container {{
      max-width: 640px;
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 28px;
    }}
    .header {{
      text-align: center;
    }}
    .title {{
      font-size: 28px;
      font-weight: 700;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #ffffff 40%, #a7f3d0 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 8px;
    }}
    .subtitle {{
      font-size: 14px;
      color: #9ca3af;
      max-width: 460px;
      line-height: 1.5;
    }}
    .badge-wrap {{
      position: relative;
      width: 380px;
      height: 380px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .canvas-bg {{
      position: absolute;
      inset: -40px;
      pointer-events: none;
    }}
    .brain-card {{
      position: relative;
      width: 360px;
      height: 360px;
      border-radius: 44px;
      background: var(--card-bg);
      border: 1px solid rgba(52, 211, 153, 0.25);
      box-shadow: 0 0 60px rgba(5, 150, 105, 0.2), inset 0 0 35px rgba(16, 185, 129, 0.08);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.3s ease, box-shadow 0.3s ease;
    }}
    .brain-card:hover {{
      transform: scale(1.02);
      box-shadow: 0 0 80px rgba(5, 150, 105, 0.32), inset 0 0 45px rgba(16, 185, 129, 0.12);
    }}
    .controls {{
      width: 100%;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 20px;
      padding: 20px 24px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      backdrop-filter: blur(12px);
    }}
    .control-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      font-size: 13px;
      color: #d1d5db;
    }}
    input[type="range"] {{
      flex: 1;
      accent-color: #34d399;
      height: 6px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 999px;
      outline: none;
    }}
    .btn-group {{
      display: flex;
      gap: 12px;
      width: 100%;
      margin-top: 4px;
    }}
    .btn {{
      flex: 1;
      padding: 12px 18px;
      border-radius: 12px;
      font-weight: 600;
      font-size: 13px;
      text-align: center;
      text-decoration: none;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      cursor: pointer;
    }}
    .btn-primary {{
      background: #10b981;
      color: #022c22;
      border: 1px solid #34d399;
    }}
    .btn-primary:hover {{
      background: #34d399;
      box-shadow: 0 0 20px rgba(52, 211, 153, 0.4);
      transform: translateY(-1px);
    }}
    .btn-secondary {{
      background: rgba(255, 255, 255, 0.06);
      color: #e5e7eb;
      border: 1px solid rgba(255, 255, 255, 0.12);
    }}
    .btn-secondary:hover {{
      background: rgba(255, 255, 255, 0.1);
      border-color: rgba(255, 255, 255, 0.25);
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1 class="title">Pentagon AI Brain</h1>
      <p class="subtitle">Autonomous Multimodal AI Workspace — 80+ NVIDIA NIM models, local document RAG, vision, web search, voice & zero-trust BYOK key security.</p>
    </div>

    <div class="badge-wrap">
      <canvas id="particles" class="canvas-bg" width="460" height="460"></canvas>
      <div class="brain-card" id="card">
        <img id="brain-svg" src="pentagon-brain-animated.svg" width="310" height="310" alt="Pentagon AI Brain" />
      </div>
    </div>

    <div class="controls">
      <div class="control-row">
        <span>Animation Speed</span>
        <input type="range" id="speed" min="0.2" max="3" step="0.1" value="1">
        <span id="speed-val" style="min-width: 36px; text-align: right; color: #34d399;">1.0x</span>
      </div>

      <div class="btn-group">
        <a href="https://pentagon-bice.vercel.app" class="btn btn-primary" target="_blank">
          🚀 Open Live App
        </a>
        <a href="https://github.com/Reddirector/Pentagon" class="btn btn-secondary" target="_blank">
          ★ GitHub Repository
        </a>
      </div>
    </div>
  </div>

  <script>
    // Particle canvas background
    const canvas = document.getElementById('particles');
    const ctx = canvas.getContext('2d');
    const particles = Array.from({{ length: 38 }}, () => ({{
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.5 + 0.5,
      alpha: Math.random() * 0.7 + 0.2,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3
    }}));

    function animate() {{
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles.forEach(p => {{
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(167, 243, 208, ${{p.alpha}})`;
        ctx.fill();
      }});
      requestAnimationFrame(animate);
    }}
    animate();

    // Speed slider
    const speedSlider = document.getElementById('speed');
    const speedVal = document.getElementById('speed-val');
    speedSlider.addEventListener('input', (e) => {{
      const val = parseFloat(e.target.value);
      speedVal.textContent = val.toFixed(1) + 'x';
    }});
  </script>
</body>
</html>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote interactive HTML demo to {output_path}")


def main() -> None:
    t0 = time.time()
    paths = load_logo_paths()

    # 1. Standalone Animated SVG
    animated_svg_docs = os.path.join(DOCS_ASSETS, "pentagon-brain-animated.svg")
    animated_svg_public = os.path.join(PUBLIC, "pentagon-brain-animated.svg")
    generate_standalone_animated_svg(paths, animated_svg_docs)
    shutil.copy2(animated_svg_docs, animated_svg_public)

    # 2. Standalone Interactive HTML Demo
    interactive_html_docs = os.path.join(DOCS_ASSETS, "brain-animation.html")
    interactive_html_public = os.path.join(PUBLIC, "brain-animation.html")
    generate_interactive_html(paths, interactive_html_docs)
    shutil.copy2(interactive_html_docs, interactive_html_public)

    # 3. High-res still PNG (frame 0)
    still_png_docs = os.path.join(DOCS_ASSETS, "pentagon-brain.png")
    still_png_public = os.path.join(PUBLIC, "pentagon-brain.png")

    # 4. Render 50 frames with headless chrome
    num_frames = 50
    fps = 25
    print(f"Rendering {num_frames} frames for perfectly looping animated GIF...")

    temp_dir = tempfile.mkdtemp(prefix="pentagon_brain_frames_")
    try:
        def render_frame(i: int) -> None:
            t = float(i) / float(num_frames)
            frame_html = render_html_frame(paths, t)
            html_file = os.path.join(temp_dir, f"frame_{i:03d}.html")
            png_file = os.path.join(temp_dir, f"frame_{i:03d}.png")
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(frame_html)
            subprocess.run([
                "google-chrome",
                "--headless=new",
                "--disable-gpu",
                "--window-size=480,480",
                f"--screenshot={png_file}",
                f"file://{html_file}",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(render_frame, range(num_frames)))

        # Copy frame 0 as the high-res hero PNG
        shutil.copy2(os.path.join(temp_dir, "frame_000.png"), still_png_docs)
        shutil.copy2(still_png_docs, still_png_public)
        print(f"Saved hero still PNG to {still_png_docs}")

        # 5. Assemble into ultra-smooth looping animated GIF with ffmpeg palettegen
        gif_docs = os.path.join(DOCS_ASSETS, "pentagon-brain-animated.gif")
        gif_public = os.path.join(PUBLIC, "pentagon-brain-animated.gif")

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(temp_dir, "frame_%03d.png"),
            "-vf", "fps=25,scale=380:380:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=192:reserve_transparent=0:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
            gif_docs,
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.copy2(gif_docs, gif_public)

        gif_size = os.path.getsize(gif_docs) / 1024.0
        print(f"Generated animated GIF: {gif_docs} ({gif_size:.1f} KB)")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"All Pentagon Brain assets generated successfully in {time.time() - t0:.2f}s!")


if __name__ == "__main__":
    main()
