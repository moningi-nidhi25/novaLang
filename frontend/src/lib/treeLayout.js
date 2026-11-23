// Tidy top-down layout for the syntax tree. Pure functions: JSON in, coordinates out.
//
// Every node gets a box (width follows its text). A parent is centred above the
// span of its children; each subtree reserves as much width as its children need,
// so boxes never overlap. Collapsed nodes lay out as leaves.

import { childList } from './astNodes'

export const NODE_H = 46
export const H_GAP = 16
export const V_GAP = 54
export const MARGIN = 24
const UI_CHAR = 7.6 // approximate glyph width (px) of the 13px UI font
const MAX_LABEL = 24

export const shortLabel = (label) =>
  label && label.length > MAX_LABEL ? `${label.slice(0, MAX_LABEL - 1)}…` : (label ?? '')

export function nodeWidth(node) {
  const text = Math.max(node.type.length, shortLabel(node.label).length)
  return Math.max(72, Math.ceil(text * UI_CHAR + 26))
}

/** Count of nodes in the whole tree (used to decide the default folding). */
export function countNodes(node) {
  return 1 + childList(node).reduce((n, c) => n + countNodes(c.node), 0)
}

/** Ids of nodes that have children and sit at or below *depth* (to fold big trees). */
export function idsDeeperThan(root, depth) {
  const out = new Set()
  const walk = (node, id, d) => {
    const kids = childList(node)
    if (kids.length && d >= depth) out.add(id)
    kids.forEach((c, i) => walk(c.node, `${id}.${i}`, d + 1))
  }
  walk(root, '0', 0)
  return out
}

export function allFoldableIds(root) {
  return idsDeeperThan(root, 0)
}

/**
 * layoutTree(root, collapsed) ->
 *   { nodes: [{ id, node, field, depth, parentId, x, y, w, h, childCount, collapsed }],
 *     edges: [{ from, to }], width, height }
 * (x, y) is the top-left corner. Ids are paths: "0", "0.1", "0.1.0", ...
 */
export function layoutTree(root, collapsed = new Set()) {
  const build = (node, id, field, depth, parentId) => {
    const kids = childList(node)
    const isCollapsed = kids.length > 0 && collapsed.has(id)
    const item = {
      id, node, field, depth, parentId, w: nodeWidth(node),
      childCount: kids.length, collapsed: isCollapsed,
      children: isCollapsed ? [] : kids.map((c, i) => build(c.node, `${id}.${i}`, c.field, depth + 1, id)),
    }
    const span = item.children.reduce((s, c) => s + c.span, 0) + H_GAP * Math.max(0, item.children.length - 1)
    item.span = Math.max(item.w, span)
    return item
  }

  const tree = build(root, '0', '', 0, null)
  const nodes = []
  const edges = []
  let maxDepth = 0

  const place = (item, left) => {
    item.x = left + (item.span - item.w) / 2
    item.y = MARGIN + item.depth * (NODE_H + V_GAP)
    maxDepth = Math.max(maxDepth, item.depth)
    nodes.push({
      id: item.id, node: item.node, field: item.field, depth: item.depth, parentId: item.parentId,
      x: item.x, y: item.y, w: item.w, h: NODE_H, childCount: item.childCount, collapsed: item.collapsed,
    })
    const kidsWidth = item.children.reduce((s, c) => s + c.span, 0) + H_GAP * Math.max(0, item.children.length - 1)
    let cursor = left + (item.span - kidsWidth) / 2
    for (const child of item.children) {
      edges.push({ from: item.id, to: child.id })
      place(child, cursor)
      cursor += child.span + H_GAP
    }
  }
  place(tree, MARGIN)

  return {
    nodes,
    edges,
    width: tree.span + 2 * MARGIN,
    height: MARGIN * 2 + (maxDepth + 1) * NODE_H + maxDepth * V_GAP,
  }
}

/** Ids from the root down to *id* (inclusive): the path to highlight when a node is selected. */
export function pathTo(layout, id) {
  const byId = new Map(layout.nodes.map((n) => [n.id, n]))
  const path = []
  for (let cur = byId.get(id); cur; cur = byId.get(cur.parentId)) path.unshift(cur.id)
  return path
}
