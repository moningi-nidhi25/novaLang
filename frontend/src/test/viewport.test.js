import { describe, expect, it } from 'vitest'
import { MAX_K, MIN_K, READABLE_K, centerOn, clamp, fitTransform, panBy, zoomAt } from '../lib/viewport'

describe('viewport math', () => {
  it('clamp keeps a value inside its range', () => {
    expect(clamp(5, 0, 3)).toBe(3)
    expect(clamp(-1, 0, 3)).toBe(0)
    expect(clamp(2, 0, 3)).toBe(2)
  })

  it('fit centers a small drawing at 100% and never enlarges it', () => {
    const t = fitTransform(800, 600, 200, 100)
    expect(t.k).toBe(1)
    expect(t.x).toBe(300)   // (800 - 200) / 2
    expect(t.y).toBe(250)   // (600 - 100) / 2
  })

  it('fit shrinks a drawing that is too large so it fits with padding', () => {
    const t = fitTransform(500, 400, 2000, 1000, 20)
    expect(t.k).toBeCloseTo(0.23)               // limited by width: (500 - 40) / 2000
    expect(2000 * t.k).toBeLessThanOrEqual(500 - 40 + 1e-9)
    expect(1000 * t.k).toBeLessThanOrEqual(400 - 40 + 1e-9)
  })

  it('fit starts a tall drawing at the top instead of cutting its first rows off', () => {
    const t = fitTransform(500, 300, 100, 5000, 24)
    expect(t.y).toBeGreaterThanOrEqual(24)
  })

  it('fit keeps a very tall drawing readable and starts at its top instead of shrinking it to a speck', () => {
    const t = fitTransform(700, 460, 300, 3000, 24)
    expect(t.k).toBe(READABLE_K)                 // not 0.14
    expect(t.y).toBe(24)                         // top of the drawing is visible
  })

  it('fit still shrinks a drawing that is too wide, even below the readable size', () => {
    const t = fitTransform(400, 460, 3000, 100, 20)
    expect(t.k).toBeLessThan(READABLE_K)
    expect(3000 * t.k).toBeLessThanOrEqual(400 - 40 + 1e-9)
  })

  it('fit survives an empty drawing or a zero-size box', () => {
    expect(fitTransform(500, 400, 0, 0)).toEqual({ k: 1, x: 0, y: 0 })
    expect(fitTransform(0, 0, 100, 100)).toEqual({ k: 1, x: 0, y: 0 })
  })

  it('zoomAt keeps the point under the cursor fixed', () => {
    const t = { k: 1, x: 30, y: 10 }
    const [px, py] = [200, 120]
    const gx = (px - t.x) / t.k   // the drawing point under the cursor
    const gy = (py - t.y) / t.k
    const z = zoomAt(t, 2, px, py)
    expect(z.k).toBe(2)
    expect(gx * z.k + z.x).toBeCloseTo(px)
    expect(gy * z.k + z.y).toBeCloseTo(py)
  })

  it('zoom is limited to the allowed range, and the view stays consistent at the limit', () => {
    const big = zoomAt({ k: MAX_K, x: 0, y: 0 }, 10, 50, 50)
    expect(big).toEqual({ k: MAX_K, x: 0, y: 0 })
    expect(zoomAt({ k: MIN_K, x: 0, y: 0 }, 0.01, 50, 50).k).toBe(MIN_K)
  })

  it('panBy moves only x and y; centerOn puts a point where asked', () => {
    expect(panBy({ k: 2, x: 1, y: 2 }, 5, -3)).toEqual({ k: 2, x: 6, y: -1 })
    const t = centerOn({ k: 2, x: 0, y: 0 }, 100, 50, 300, 200)
    expect(100 * t.k + t.x).toBe(300)
    expect(50 * t.k + t.y).toBe(200)
  })
})
