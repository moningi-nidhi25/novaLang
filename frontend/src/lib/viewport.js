// Pure math for the pan / zoom view of a graph. A view is {k, x, y}: the drawing is
// scaled by k and then moved by (x, y) pixels. No DOM here, so it is easy to test.

export const MIN_K = 0.05
export const MAX_K = 3
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

export const READABLE_K = 0.6 // below this, text in the diagram is too small to read

/**
 * The view that shows the drawing (w x h) in a box (cw x ch): everything at once when that
 * stays readable, otherwise the top of the drawing at a readable size (pan down to see the
 * rest). Never enlarges past 100%. A drawing too wide for the box is always shrunk to fit its width.
 */
export function fitTransform(cw, ch, w, h, pad = 24) {
  if (!(w > 0) || !(h > 0) || !(cw > 0) || !(ch > 0)) return { k: 1, x: 0, y: 0 }
  const byWidth = Math.min((cw - 2 * pad) / w, 1)
  const everything = Math.min(byWidth, (ch - 2 * pad) / h)
  const k = clamp(Math.max(everything, Math.min(byWidth, READABLE_K)), MIN_K, MAX_K)
  return { k, x: (cw - w * k) / 2, y: Math.max(pad, (ch - h * k) / 2) }
}

/** Zoom by `factor` keeping the drawing point under the pixel (px, py) where it is. */
export function zoomAt(t, factor, px, py) {
  const k = clamp(t.k * factor, MIN_K, MAX_K)
  const r = k / t.k
  return { k, x: px - (px - t.x) * r, y: py - (py - t.y) * r }
}

export const panBy = (t, dx, dy) => ({ ...t, x: t.x + dx, y: t.y + dy })

/** Move the view so the drawing point (gx, gy) sits at the pixel (px, py), keeping the zoom. */
export const centerOn = (t, gx, gy, px, py) => ({ ...t, x: px - gx * t.k, y: py - gy * t.k })
