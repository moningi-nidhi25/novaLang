// Layout for the two drawn graphs. Pure functions: data in, coordinates out.
//
//  * layoutTree  - the AST, top-down. Each node is centered over its children.
//  * layoutCfg   - a control-flow graph in layers. Compiler concept: a loop is a
//                  "back edge" (it returns to a block that already ran). Back edges
//                  are removed to rank the blocks top to bottom, then drawn on the right.

const CHAR = 7.4 // width of one monospace character at the drawing's font size
const textWidth = (s) => Math.ceil(String(s).length * CHAR)

export const shorten = (s, max) => {
  const t = String(s)
  return t.length > max ? `${t.slice(0, max - 1)}…` : t
}

// ----------------------------------------------------------------------
// AST
// ----------------------------------------------------------------------
export const TREE = { nodeH: 46, hgap: 14, vgap: 46 }

export function astKind(type) {
  if (/^(Literal|Identifier|ArrayLiteral)$/.test(type)) return 'leaf'
  if (/(Statement|Declaration|Block|Program)$/.test(type)) return 'stmt'
  return 'expr'
}

export function astNodeWidth(node) {
  const label = node.label ? shorten(node.label, 18) : ''
  return Math.max(64, textWidth(node.type) + 24, textWidth(label) + 24)
}

/**
 * childrenOf(node) -> [[fieldName, childNode], ...]. Nodes whose id is in `collapsed`
 * are drawn without their children. Ids are paths: "0" is the root, "0.2" its third child.
 */
export function layoutTree(root, childrenOf, { collapsed = new Set() } = {}) {
  const build = (node, id, depth, parent, field) => {
    const all = childrenOf(node)
    const shown = collapsed.has(id) ? [] : all
    const children = shown.map(([f, c], i) => build(c, `${id}.${i}`, depth + 1, id, f))
    const w = astNodeWidth(node)
    const childrenW = children.reduce((s, c) => s + c.sub, 0) + TREE.hgap * Math.max(0, children.length - 1)
    return {
      id, node, field, depth, parent, w, h: TREE.nodeH, children,
      hasChildren: all.length > 0, collapsed: collapsed.has(id),
      sub: Math.max(w, childrenW), childrenW,
    }
  }
  const top = build(root, '0', 0, null, null)

  const nodes = []
  const edges = []
  let maxDepth = 0
  const place = (n, left) => {
    n.y = n.depth * (TREE.nodeH + TREE.vgap)
    maxDepth = Math.max(maxDepth, n.depth)
    let cursor = left + (n.sub - n.childrenW) / 2
    for (const c of n.children) {
      edges.push({ from: n.id, to: c.id, field: c.field })
      place(c, cursor)
      cursor += c.sub + TREE.hgap
    }
    if (n.children.length === 0) {
      n.x = left + (n.sub - n.w) / 2
    } else {
      // sit over the middle of the first and last child, but stay inside our own column
      const first = n.children[0]
      const last = n.children[n.children.length - 1]
      const mid = (first.x + first.w / 2 + last.x + last.w / 2) / 2
      n.x = Math.min(Math.max(mid - n.w / 2, left), left + n.sub - n.w)
    }
    nodes.push(n)
  }
  place(top, 0)
  return { nodes, edges, width: top.sub, height: (maxDepth + 1) * TREE.nodeH + maxDepth * TREE.vgap }
}

/** Ids from the root down to `id`, e.g. "0.1.2" -> ["0", "0.1", "0.1.2"]. */
export function pathTo(id) {
  const parts = id.split('.')
  return parts.map((_, i) => parts.slice(0, i + 1).join('.'))
}

// ----------------------------------------------------------------------
// CFG
// ----------------------------------------------------------------------
export const CFG = {
  head: 26, line: 20, padX: 12, padBottom: 8, hgap: 44, vgap: 58, maxText: 44, loopGap: 18, laneW: 14,
}

export const instructionText = (ins) => shorten(ins.text, CFG.maxText)

function blockSize(block) {
  const widest = Math.max(
    textWidth(`${block.name}  unreachable`),
    ...block.instructions.map((i) => textWidth(`00  ${instructionText(i)}`)),
  )
  return {
    w: Math.max(110, widest + 2 * CFG.padX),
    h: CFG.head + block.instructions.length * CFG.line + CFG.padBottom,
  }
}

/** Split edges into forward edges and back edges (an edge to a block still being explored). */
export function classifyEdges(blocks, edges, entry) {
  const out = new Map(blocks.map((b) => [b.name, []]))
  edges.forEach((e, i) => out.get(e.source)?.push([e.target, i]))
  const state = new Map() // undefined = new, 1 = on the current path, 2 = done
  const back = new Set()
  const visit = (name) => {
    state.set(name, 1)
    for (const [target, i] of out.get(name) ?? []) {
      if (state.get(target) === 1) back.add(i)
      else if (!state.has(target)) visit(target)
    }
    state.set(name, 2)
  }
  if (entry && out.has(entry)) visit(entry)
  for (const b of blocks) if (!state.has(b.name)) visit(b.name) // unreachable code too
  return back
}

/** An SVG path through `points` (axis-aligned runs) with rounded corners. */
export function roundedPath(points, radius = 10) {
  const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y)
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const [a, b, c] = [points[i - 1], points[i], points[i + 1]]
    const r = Math.min(radius, dist(a, b) / 2, dist(b, c) / 2)
    const inX = Math.sign(b.x - a.x)
    const inY = Math.sign(b.y - a.y)
    const outX = Math.sign(c.x - b.x)
    const outY = Math.sign(c.y - b.y)
    d += ` L ${b.x - inX * r} ${b.y - inY * r} Q ${b.x} ${b.y} ${b.x + outX * r} ${b.y + outY * r}`
  }
  const last = points[points.length - 1]
  return `${d} L ${last.x} ${last.y}`
}

/**
 * Layered layout (Sugiyama style):
 *  1. back edges (loops) are set aside; the remaining edges form a DAG, whose longest paths give each block a row;
 *  2. an edge that skips rows gets a thin "lane" in every row it passes, so it can never run through a block;
 *  3. blocks in a row are ordered under the average position of their parents, then each row is centered;
 *  4. loop edges leave a block's bottom, run through the gap between rows, up the right side of the
 *     drawing, and come back down into the top of the block they return to.
 */
export function layoutCfg(graph) {
  const { blocks, edges } = graph
  if (blocks.length === 0) return { nodes: [], edges: [], width: 0, height: 0 }
  const back = classifyEdges(blocks, edges, graph.entry)

  // 1. rows
  const fwdPreds = new Map(blocks.map((b) => [b.name, []]))
  edges.forEach((e, i) => { if (!back.has(i)) fwdPreds.get(e.target)?.push(e.source) })
  const rank = new Map()
  const rankOf = (name) => {
    if (!rank.has(name)) {
      rank.set(name, 0)
      rank.set(name, Math.max(-1, ...fwdPreds.get(name).map(rankOf)) + 1)
    }
    return rank.get(name)
  }
  blocks.forEach((b) => rankOf(b.name))

  // 2. lanes for edges that skip rows: chain[i] = names of the lane items edge i passes through
  const items = new Map(blocks.map((b) => [b.name, { name: b.name, lane: false, ...blockSize(b), block: b }]))
  const preds = new Map(blocks.map((b) => [b.name, []]))
  const succs = new Map(blocks.map((b) => [b.name, []]))
  const link = (a, b) => { succs.get(a).push(b); preds.get(b).push(a) }
  const chain = new Map()
  edges.forEach((e, i) => {
    if (back.has(i)) return
    let prev = e.source
    const lanes = []
    for (let r = rank.get(e.source) + 1; r < rank.get(e.target); r++) {
      const name = `~${i}.${r}`
      items.set(name, { name, lane: true, w: CFG.laneW, h: 0, rank: r })
      preds.set(name, [])
      succs.set(name, [])
      rank.set(name, r)
      link(prev, name)
      lanes.push(name)
      prev = name
    }
    link(prev, e.target)
    chain.set(i, lanes)
  })

  // 3. order within rows
  const rows = []
  for (const name of items.keys()) (rows[rank.get(name)] ??= []).push(name)
  const pos = new Map()
  rows.forEach((row) => row.forEach((n, i) => pos.set(n, i)))
  const sweep = (r, neighbours) => {
    const centre = (n) => {
      const ns = neighbours.get(n)
      return ns.length ? ns.reduce((s, m) => s + pos.get(m), 0) / ns.length : pos.get(n)
    }
    rows[r].sort((a, b) => centre(a) - centre(b))
    rows[r].forEach((n, i) => pos.set(n, i))
  }
  for (let r = 1; r < rows.length; r++) sweep(r, preds)
  for (let r = rows.length - 2; r >= 0; r--) sweep(r, succs)
  for (let r = 1; r < rows.length; r++) sweep(r, preds)

  // coordinates
  const rowWidth = rows.map((row) => row.reduce((s, n) => s + items.get(n).w, 0) + CFG.hgap * (row.length - 1))
  const innerW = Math.max(...rowWidth)
  const margin = CFG.vgap / 2 // room above the first row and below the last for loop edges
  const rowTop = []
  const rowBottom = []
  const placed = new Map()
  let y = margin
  rows.forEach((row, r) => {
    let x = (innerW - rowWidth[r]) / 2
    const rowH = Math.max(12, ...row.map((n) => items.get(n).h))
    rowTop[r] = y
    rowBottom[r] = y + rowH
    row.forEach((n) => {
      const it = items.get(n)
      placed.set(n, { ...it, x, y })
      x += it.w + CFG.hgap
    })
    y += rowH + CFG.vgap
  })
  const height = y - CFG.vgap + margin

  // 4. edges
  const outgoing = new Map(blocks.map((b) => [b.name, []]))
  edges.forEach((e, i) => outgoing.get(e.source).push(i))
  const exitX = (s, i) => {
    const mine = outgoing.get(s.name)
    const slot = mine.indexOf(i) - (mine.length - 1) / 2
    return s.x + s.w / 2 + slot * Math.min(44, s.w / (mine.length + 1))
  }

  let loops = 0
  const drawn = edges.map((e, i) => {
    const s = placed.get(e.source)
    const t = placed.get(e.target)
    const sx = exitX(s, i)
    const label = { x: sx + 6, y: s.y + s.h + 16 }
    if (back.has(i)) {
      const k = loops++
      const bx = innerW + CFG.loopGap * (k + 1)
      const lane = ((k % 4) - 1.5) * 5 // keeps neighbouring loop edges from sharing a line
      const below = rowBottom[rank.get(e.source)] + CFG.vgap / 2 + lane
      const above = rowTop[rank.get(e.target)] - CFG.vgap / 2 + lane
      const ex = t.x + t.w - Math.min(26, t.w * 0.25)
      const points = [
        { x: sx, y: s.y + s.h }, { x: sx, y: below }, { x: bx, y: below },
        { x: bx, y: above }, { x: ex, y: above }, { x: ex, y: t.y },
      ]
      return { ...e, back: true, points, d: roundedPath(points), label }
    }
    const points = [{ x: sx, y: s.y + s.h }]
    for (const name of chain.get(i)) {
      const lane = placed.get(name)
      const cx = lane.x + lane.w / 2
      points.push({ x: cx, y: rowTop[lane.rank] }, { x: cx, y: rowBottom[lane.rank] })
    }
    points.push({ x: t.x + t.w / 2, y: t.y })
    let d = `M ${points[0].x} ${points[0].y}`
    for (let j = 1; j < points.length; j++) {
      const a = points[j - 1]
      const b = points[j]
      const dy = (b.y - a.y) / 2
      d += a.x === b.x ? ` L ${b.x} ${b.y}` : ` C ${a.x} ${a.y + dy} ${b.x} ${b.y - dy} ${b.x} ${b.y}`
    }
    return { ...e, back: false, points, d, label }
  })

  const nodes = [...placed.values()].filter((n) => !n.lane).map(({ name, block, x, y, w, h }) => ({ name, block, x, y, w, h }))
  return { nodes, edges: drawn, width: innerW + CFG.loopGap * (loops + 1), height }
}
