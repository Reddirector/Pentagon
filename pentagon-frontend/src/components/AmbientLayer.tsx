import { useEffect, useRef, useSyncExternalStore } from 'react'
import {
  applyAutoDowngrade,
  dotCount,
  getAmbientMode,
  getAmbientState,
  subscribeAmbient,
} from '../lib/ambient'

// L4 constellation: one canvas, 30fps cap, DPR capped at 1.5, paused when the
// tab is hidden. Dots twinkle and drift; nearby dots are joined by faint lines.
// The pointer pushes the field aside: dots near the cursor are displaced away
// from it at draw time, so hovering parts the constellation and the effect
// unwinds the moment the cursor leaves. Displacing at draw time rather than
// adding impulse to each dot means the response is instant and cannot pump
// energy into the drift over time.
function Constellation() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mode = useSyncExternalStore(subscribeAmbient, getAmbientMode)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || mode === 'off') return
    const context = canvas.getContext('2d')
    if (!context) return

    const calm = mode === 'calm'
    const speed = calm ? 0.4 : 1
    // How far a dot is shoved clear of the cursor, and over what distance.
    const pushRadius = calm ? 68 : 104
    const pushStrength = calm ? 26 : 46
    let width = 0
    let height = 0
    let dots: { x: number; y: number; vx: number; vy: number; phase: number }[] = []
    // Where each dot is actually painted this frame, after the cursor has
    // pushed it. Links are drawn from these too, so the whole field parts
    // together instead of the lines stretching across the gap.
    let drawnX: number[] = []
    let drawnY: number[] = []

    const pointer = { x: 0, y: 0, active: false }
    // Eased so the field settles into place instead of snapping, and so
    // leaving the window fades the parting back out rather than cutting it.
    let influence = 0

    const onPointerMove = (event: PointerEvent) => {
      // Touch and pen have no hover, so they should not part the field.
      if (event.pointerType && event.pointerType !== 'mouse') return
      pointer.x = event.clientX
      pointer.y = event.clientY
      pointer.active = true
    }
    const onPointerLeave = () => {
      pointer.active = false
    }

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
      width = window.innerWidth
      height = window.innerHeight
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      const count = dotCount(mode, width * height)
      drawnX = new Array<number>(count)
      drawnY = new Array<number>(count)
      dots = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 2 * speed,
        vy: (Math.random() - 0.5) * 2 * speed,
        phase: Math.random() * Math.PI * 2,
      }))
    }

    resize()
    window.addEventListener('resize', resize)
    // The canvas is pointer-events-none, so the cursor is tracked on the window.
    window.addEventListener('pointermove', onPointerMove, { passive: true })
    document.documentElement.addEventListener('pointerleave', onPointerLeave)

    let frame = 0
    let last = performance.now()
    let slowFrames = 0
    let raf = 0

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw)
      const delta = now - last
      // Auto-guard: if we are consistently missing frames, shed a quality level.
      if (delta > 45) slowFrames += 1
      else slowFrames = Math.max(0, slowFrames - 1)
      if (slowFrames > 90) {
        slowFrames = 0
        applyAutoDowngrade()
        return
      }
      // 30fps cap regardless of display refresh rate.
      if (delta < 33) return
      last = now
      if (document.hidden) return
      frame += 1

      context.clearRect(0, 0, width, height)
      const linkDistance = calm ? 96 : 128

      for (const dot of dots) {
        dot.x += dot.vx
        dot.y += dot.vy
        if (dot.x < -10) dot.x = width + 10
        if (dot.x > width + 10) dot.x = -10
        if (dot.y < -10) dot.y = height + 10
        if (dot.y > height + 10) dot.y = -10
      }

      influence += ((pointer.active ? 1 : 0) - influence) * 0.18
      if (influence < 0.002) influence = 0

      const reach = pushRadius * pushRadius
      for (let i = 0; i < dots.length; i += 1) {
        const dot = dots[i]
        let x = dot.x
        let y = dot.y
        if (influence > 0) {
          const dx = x - pointer.x
          const dy = y - pointer.y
          const distanceSquared = dx * dx + dy * dy
          if (distanceSquared < reach) {
            const distance = Math.sqrt(distanceSquared)
            // Directly under the cursor there is no direction to push along,
            // so nudge straight up rather than dividing by zero.
            const nx = distance > 0.001 ? dx / distance : 0
            const ny = distance > 0.001 ? dy / distance : -1
            // Squared falloff: gentle at the rim, firmest at the cursor.
            const falloff = 1 - distance / pushRadius
            const push = pushStrength * falloff * falloff * influence
            x += nx * push
            y += ny * push
          }
        }
        drawnX[i] = x
        drawnY[i] = y
      }

      context.lineWidth = 1
      for (let i = 0; i < dots.length; i += 1) {
        for (let j = i + 1; j < dots.length; j += 1) {
          const dx = drawnX[i] - drawnX[j]
          const dy = drawnY[i] - drawnY[j]
          const distance = Math.hypot(dx, dy)
          if (distance > linkDistance) continue
          context.strokeStyle = `rgba(255, 255, 255, ${(1 - distance / linkDistance) * 0.1})`
          context.beginPath()
          context.moveTo(drawnX[i], drawnY[i])
          context.lineTo(drawnX[j], drawnY[j])
          context.stroke()
        }
      }

      for (let i = 0; i < dots.length; i += 1) {
        const twinkle = 0.28 + Math.sin(frame / 22 + dots[i].phase) * 0.18
        context.fillStyle = `rgba(255, 255, 255, ${Math.max(0.06, twinkle)})`
        context.beginPath()
        context.arc(drawnX[i], drawnY[i], calm ? 1 : 1.4, 0, Math.PI * 2)
        context.fill()
      }
    }

    raf = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', onPointerMove)
      document.documentElement.removeEventListener('pointerleave', onPointerLeave)
    }
  }, [mode])

  if (mode === 'off') return null
  return <canvas ref={canvasRef} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />
}

// L0-L6, mounted once at the app root as a fixed, inert layer.
export function AmbientLayer() {
  const mode = useSyncExternalStore(subscribeAmbient, getAmbientMode)
  const state = useSyncExternalStore(subscribeAmbient, getAmbientState)

  useEffect(() => {
    const root = document.documentElement
    root.dataset.ambient = mode === 'off' ? 'off' : state
    root.dataset.ambientMode = mode
    return () => {
      delete root.dataset.ambient
      delete root.dataset.ambientMode
    }
  }, [state, mode])

  if (mode === 'off') return null

  const calm = mode === 'calm'

  return (
    <div aria-hidden="true" className="ambient-root" data-state={state} data-mode={mode}>
      <div className="ambient-aurora ambient-aurora-a" />
      <div className="ambient-aurora ambient-aurora-b" />
      <div className="ambient-aurora ambient-aurora-c" />
      <div className="ambient-warm" />

      {/* L3 orbits: concentric circles partly off-screen. Never polygons. */}
      <svg className="ambient-orbits" viewBox="0 0 1000 700" fill="none" preserveAspectRatio="xMidYMid slice">
        <circle cx="500" cy="350" r="420" stroke="rgb(255 255 255 / 0.05)" strokeWidth="1" />
        <circle cx="500" cy="350" r="610" stroke="rgb(255 255 255 / 0.035)" strokeWidth="1" />
        {calm ? null : <circle cx="500" cy="350" r="820" stroke="rgb(255 255 255 / 0.022)" strokeWidth="1" />}
      </svg>

      <Constellation />

      {/* L5 grain: static SVG noise, no animation. */}
      <div className="ambient-grain" />

      {/* L6 vignette keeps the reading column legible. */}
      <div className="ambient-vignette" />
    </div>
  )
}