import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { MAX_K, MIN_K, fitTransform, panBy, zoomAt } from '../lib/viewport'

const DRAG_THRESHOLD = 4 // pixels: a smaller movement is a click, not a pan

/**
 * An SVG viewport you can zoom (wheel, buttons, + / -), pan (drag, arrow keys) and reset
 * (Fit, key 0). `width` x `height` is the size of the drawing in its own units. The
 * children draw into that coordinate space and receive the id of the arrow-head markers.
 */
export default function GraphCanvas({ width, height, label, children, fitKey = '' }) {
  const markerId = useId().replace(/:/g, '')
  const box = useRef(null)
  const moved = useRef(false)
  const [size, setSize] = useState({ w: 640, h: 420 })
  const [view, setView] = useState({ k: 1, x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const touched = useRef(false) // once the learner moves the view, stop re-fitting automatically

  // keep `size` equal to the on-screen box
  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    const read = () => setSize({ w: el.clientWidth || 640, h: el.clientHeight || 420 })
    read()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fit = useCallback(() => {
    touched.current = false
    setView(fitTransform(size.w, size.h, width, height))
  }, [size.w, size.h, width, height])

  // a new drawing (different program, collapsed node, other function) starts fitted
  useEffect(() => { touched.current = false }, [fitKey])
  useEffect(() => {
    if (!touched.current) setView(fitTransform(size.w, size.h, width, height))
  }, [size.w, size.h, width, height, fitKey])

  const change = useCallback((fn) => { touched.current = true; setView(fn) }, [])
  const zoomCentre = (factor) => change((t) => zoomAt(t, factor, size.w / 2, size.h / 2))

  // wheel zoom needs a non-passive listener, otherwise the page scrolls too
  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    const onWheel = (e) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const factor = Math.exp(-e.deltaY * 0.0015)
      change((t) => zoomAt(t, factor, e.clientX - r.left, e.clientY - r.top))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [change])

  // Dragging uses window listeners, not pointer capture: capture would swallow the
  // click on a node and the node could no longer be selected.
  const onPointerDown = (e) => {
    if (e.button !== 0) return
    moved.current = false
    let last = { x: e.clientX, y: e.clientY }
    const start = { ...last }
    setDragging(true)
    const move = (ev) => {
      if (Math.hypot(ev.clientX - start.x, ev.clientY - start.y) > DRAG_THRESHOLD) moved.current = true
      if (!moved.current) return
      const dx = ev.clientX - last.x
      const dy = ev.clientY - last.y
      last = { x: ev.clientX, y: ev.clientY }
      change((t) => panBy(t, dx, dy))
    }
    const up = () => {
      setDragging(false)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const onClickCapture = (e) => {
    if (moved.current) { // the pointer travelled: that was a pan, so do not "click" what it ended on
      e.stopPropagation()
      moved.current = false
    }
  }

  const onKeyDown = (e) => {
    if (e.target !== box.current) return // keys on a node belong to the node
    const step = 40
    const keys = {
      '+': () => zoomCentre(1.25), '=': () => zoomCentre(1.25), '-': () => zoomCentre(0.8), '0': fit,
      ArrowLeft: () => change((t) => panBy(t, step, 0)), ArrowRight: () => change((t) => panBy(t, -step, 0)),
      ArrowUp: () => change((t) => panBy(t, 0, step)), ArrowDown: () => change((t) => panBy(t, 0, -step)),
    }
    if (keys[e.key]) { e.preventDefault(); keys[e.key]() }
  }

  return (
    <div className="graph">
      <div className="graph-bar">
        <button type="button" className="btn small" aria-label="Zoom in" onClick={() => zoomCentre(1.25)}
                disabled={view.k >= MAX_K}>+</button>
        <button type="button" className="btn small" aria-label="Zoom out" onClick={() => zoomCentre(0.8)}
                disabled={view.k <= MIN_K}>−</button>
        <button type="button" className="btn small" onClick={fit}>Fit to view</button>
        <span className="muted graph-zoom" aria-live="off">{Math.round(view.k * 100)}%</span>
        <span className="muted graph-hint">Scroll to zoom, drag to pan.</span>
      </div>
      <div
        ref={box}
        className="graph-viewport"
        data-dragging={dragging || undefined}
        role="group"
        aria-label={label}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onClickCapture={onClickCapture}
        onKeyDown={onKeyDown}
      >
        <svg width="100%" height="100%" role="img" aria-label={label}>
          <defs>
            {['plain', 'true', 'false', 'hot'].map((kind) => (
              <marker key={kind} id={`${markerId}-${kind}`} className={`arrow arrow-${kind}`} viewBox="0 0 10 10"
                      refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
            ))}
          </defs>
          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            {children(markerId)}
          </g>
        </svg>
      </div>
    </div>
  )
}
