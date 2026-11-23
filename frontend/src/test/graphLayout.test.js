import { describe, expect, it } from 'vitest'
import { factorial, branches, loops, stage } from './fixtures'
import { childrenOf } from '../components/AstGraph'
import {
  CFG, TREE, astKind, classifyEdges, layoutCfg, layoutTree, pathTo, shorten,
} from '../lib/graphLayout'

const astRoot = (r) => stage(r, 'ast').data
const countNodes = (n) => 1 + childrenOf(n).reduce((s, [, c]) => s + countNodes(c), 0)
const cfgOf = (r, fn = 'main') => stage(r, 'cfg').data.functions.find((g) => g.function === fn)
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h

describe('shorten / astKind / pathTo', () => {
  it('shortens long text with an ellipsis and leaves short text alone', () => {
    expect(shorten('abc', 5)).toBe('abc')
    expect(shorten('abcdefgh', 5)).toBe('abcd…')
    expect(shorten('abcde', 5)).toBe('abcde')
  })
  it('groups node types for coloring', () => {
    expect(astKind('Literal')).toBe('leaf')
    expect(astKind('Identifier')).toBe('leaf')
    expect(astKind('IfStatement')).toBe('stmt')
    expect(astKind('VariableDeclaration')).toBe('stmt')
    expect(astKind('Program')).toBe('stmt')
    expect(astKind('BinaryExpression')).toBe('expr')
  })
  it('pathTo lists the ids from the root down', () => {
    expect(pathTo('0')).toEqual(['0'])
    expect(pathTo('0.1.2')).toEqual(['0', '0.1', '0.1.2'])
  })
})

describe('layoutTree (syntax tree)', () => {
  const root = astRoot(factorial)
  const layout = layoutTree(root, childrenOf)

  it('draws every node once, joined by one edge each (a tree has nodes - 1 edges)', () => {
    expect(layout.nodes).toHaveLength(countNodes(root))
    expect(layout.edges).toHaveLength(layout.nodes.length - 1)
    expect(new Set(layout.nodes.map((n) => n.id)).size).toBe(layout.nodes.length)
  })

  it('puts the root on top and each child exactly one level below its parent', () => {
    const byId = Object.fromEntries(layout.nodes.map((n) => [n.id, n]))
    expect(byId['0'].y).toBe(0)
    for (const e of layout.edges) expect(byId[e.to].y - byId[e.from].y).toBe(TREE.nodeH + TREE.vgap)
  })

  it('never lets two nodes overlap', () => {
    for (let i = 0; i < layout.nodes.length; i++) {
      for (let j = i + 1; j < layout.nodes.length; j++) {
        expect(overlap(layout.nodes[i], layout.nodes[j])).toBe(false)
      }
    }
  })

  it('keeps nodes on one level at least the gap apart', () => {
    const levels = {}
    layout.nodes.forEach((n) => { (levels[n.y] ??= []).push(n) })
    for (const row of Object.values(levels)) {
      row.sort((a, b) => a.x - b.x)
      for (let i = 1; i < row.length; i++) expect(row[i].x - (row[i - 1].x + row[i - 1].w)).toBeGreaterThanOrEqual(TREE.hgap - 1e-9)
    }
  })

  it('centers a parent over its first and last child', () => {
    const byId = Object.fromEntries(layout.nodes.map((n) => [n.id, n]))
    const kids = (id) => layout.edges.filter((e) => e.from === id).map((e) => byId[e.to])
    for (const n of layout.nodes) {
      const k = kids(n.id)
      if (!k.length) continue
      const left = k[0].x
      const right = k[k.length - 1].x + k[k.length - 1].w
      if (n.w > right - left) continue   // a wide label over narrow children is kept inside its column instead
      const mid = ((k[0].x + k[0].w / 2) + (k[k.length - 1].x + k[k.length - 1].w / 2)) / 2
      expect(n.x + n.w / 2).toBeCloseTo(mid)
    }
  })

  it('fits the reported size around all nodes', () => {
    for (const n of layout.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(-1e-9)
      expect(n.x + n.w).toBeLessThanOrEqual(layout.width + 1e-9)
      expect(n.y + n.h).toBeLessThanOrEqual(layout.height + 1e-9)
    }
  })

  it('collapsing a node hides its whole subtree but keeps the node', () => {
    const full = layout.nodes.find((n) => n.id === '0.0')   // the function declaration
    const sub = layout.nodes.filter((n) => n.id.startsWith('0.0.')).length
    expect(sub).toBeGreaterThan(0)
    const small = layoutTree(root, childrenOf, { collapsed: new Set(['0.0']) })
    expect(small.nodes).toHaveLength(layout.nodes.length - sub)
    const kept = small.nodes.find((n) => n.id === '0.0')
    expect(kept.collapsed).toBe(true)
    expect(kept.hasChildren).toBe(true)
    expect(full.collapsed).toBe(false)
  })

  it('a program with no statements is a single node', () => {
    const one = layoutTree({ type: 'Program', label: '', line: 1, column: 1, body: [] }, childrenOf)
    expect(one.nodes).toHaveLength(1)
    expect(one.edges).toHaveLength(0)
    expect(one.height).toBe(TREE.nodeH)
  })

  it('gives wider boxes to longer labels', () => {
    const w = (label) => layoutTree({ type: 'Identifier', label, line: 1, column: 1 }, childrenOf).nodes[0].w
    expect(w('a_much_longer_name')).toBeGreaterThan(w('x'))
  })
})

describe('classifyEdges (finding loops)', () => {
  const b = (...names) => names.map((name) => ({ name }))
  const e = (s, t) => ({ source: s, target: t })

  it('a diamond (if / else) has no back edge', () => {
    const edges = [e('A', 'B'), e('A', 'C'), e('B', 'D'), e('C', 'D')]
    expect(classifyEdges(b('A', 'B', 'C', 'D'), edges, 'A').size).toBe(0)
  })
  it('a while loop has exactly one back edge: the jump back to the test', () => {
    const edges = [e('A', 'T'), e('T', 'Body'), e('T', 'Exit'), e('Body', 'T')]
    const back = classifyEdges(b('A', 'T', 'Body', 'Exit'), edges, 'A')
    expect([...back]).toEqual([3])
  })
  it('a block that jumps to itself is a back edge', () => {
    expect([...classifyEdges(b('A', 'S'), [e('A', 'S'), e('S', 'S')], 'A')]).toEqual([1])
  })
  it('nested loops give two back edges', () => {
    const edges = [e('A', 'O'), e('O', 'I'), e('I', 'I2'), e('I2', 'I'), e('I2', 'O'), e('O', 'X')]
    expect(classifyEdges(b('A', 'O', 'I', 'I2', 'X'), edges, 'A').size).toBe(2)
  })
  it('blocks that cannot be reached are still classified', () => {
    const edges = [e('A', 'B'), e('Dead1', 'Dead2'), e('Dead2', 'Dead1')]
    const back = classifyEdges(b('A', 'B', 'Dead1', 'Dead2'), edges, 'A')
    expect(back.size).toBe(1)
  })
})

describe('layoutCfg (control-flow graph)', () => {
  it('lays out every block of every example, with no overlapping boxes', () => {
    for (const r of [factorial, branches, loops]) {
      for (const g of stage(r, 'cfg').data.functions) {
        const l = layoutCfg(g)
        expect(l.nodes).toHaveLength(g.blocks.length)
        for (let i = 0; i < l.nodes.length; i++) {
          for (let j = i + 1; j < l.nodes.length; j++) expect(overlap(l.nodes[i], l.nodes[j])).toBe(false)
        }
      }
    }
  })

  it('draws every edge, and forward edges always point downward', () => {
    const g = cfgOf(loops)
    const l = layoutCfg(g)
    const at = Object.fromEntries(l.nodes.map((n) => [n.name, n]))
    expect(l.edges).toHaveLength(g.edges.length)
    for (const e of l.edges) {
      if (!e.back) expect(at[e.target].y).toBeGreaterThan(at[e.source].y)
    }
  })

  it('the loop program has back edges and they arrive at an earlier or equal row', () => {
    const l = layoutCfg(cfgOf(loops))
    const at = Object.fromEntries(l.nodes.map((n) => [n.name, n]))
    const back = l.edges.filter((e) => e.back)
    expect(back.length).toBeGreaterThanOrEqual(2)          // loops.nova has several loops
    for (const e of back) expect(at[e.target].y).toBeLessThanOrEqual(at[e.source].y)
  })

  it('loop edges run up the right side of the drawing, past every block', () => {
    const l = layoutCfg(cfgOf(loops))
    const widest = Math.max(...l.nodes.map((n) => n.x + n.w))
    for (const e of l.edges.filter((x) => x.back)) {
      expect(Math.max(...e.points.map((p) => p.x))).toBeGreaterThan(widest)
    }
    expect(l.width).toBeGreaterThan(widest)
  })

  it('a loop edge leaves the bottom of its block and arrives at the top of its target', () => {
    const l = layoutCfg(cfgOf(loops))
    const at = Object.fromEntries(l.nodes.map((n) => [n.name, n]))
    for (const e of l.edges.filter((x) => x.back)) {
      const first = e.points[0]
      const last = e.points[e.points.length - 1]
      expect(first.y).toBe(at[e.source].y + at[e.source].h)
      expect(last.y).toBe(at[e.target].y)
    }
  })

  it('no straight run of any edge passes through a block (the reason long edges get lanes)', () => {
    const inside = (n, x, y) => x > n.x && x < n.x + n.w && y > n.y && y < n.y + n.h
    for (const r of [factorial, branches, loops]) {
      for (const g of stage(r, 'cfg').data.functions) {
        const l = layoutCfg(g)
        for (const e of l.edges) {
          for (let i = 1; i < e.points.length; i++) {
            const [a, b] = [e.points[i - 1], e.points[i]]
            if (a.x !== b.x && a.y !== b.y) continue             // a curve between rows
            for (let s = 0; s <= 20; s++) {                         // sample along the run
              const x = a.x + ((b.x - a.x) * s) / 20
              const y = a.y + ((b.y - a.y) * s) / 20
              for (const n of l.nodes) expect(inside(n, x, y)).toBe(false)
            }
          }
        }
      }
    }
  })

  it('an edge that skips rows gets a lane in each row it crosses', () => {
    // A -> B -> C -> D, plus A -> D skipping two rows
    const g = {
      entry: 'A',
      blocks: ['A', 'B', 'C', 'D'].map((name, i) => ({ id: i + 1, name, instructions: [{ text: 'x', index: i }] })),
      edges: [['A', 'B'], ['B', 'C'], ['C', 'D'], ['A', 'D']].map(([source, target]) => ({ source, target, kind: 'next' })),
    }
    const l = layoutCfg(g)
    const skip = l.edges[3]
    expect(skip.points).toHaveLength(2 + 2 * 2)        // start, end, plus top and bottom in two rows
    const at = Object.fromEntries(l.nodes.map((n) => [n.name, n]))
    expect(at.B.x + at.B.w).toBeLessThan(Math.min(...skip.points.slice(1, -1).map((p) => p.x)) + 1e-9)
  })

  it('the entry block is the top row', () => {
    for (const r of [factorial, branches, loops]) {
      const g = cfgOf(r)
      const l = layoutCfg(g)
      expect(l.nodes.find((n) => n.name === g.entry).y).toBe(Math.min(...l.nodes.map((n) => n.y)))
    }
  })

  it('a block is as tall as its instructions need', () => {
    const l = layoutCfg(cfgOf(branches))
    for (const n of l.nodes) {
      expect(n.h).toBeGreaterThanOrEqual(CFG.head + n.block.instructions.length * CFG.line)
    }
  })

  it('splits the two outcomes of a condition so the arrows leave from different points', () => {
    const l = layoutCfg(cfgOf(branches))
    const byNode = {}
    l.edges.forEach((e) => { (byNode[e.source] ??= []).push(e) })
    const pair = Object.values(byNode).find((es) => es.length === 2 && es.every((e) => !e.back))
    expect(pair).toBeTruthy()
    const startX = (e) => Number(e.d.split(' ')[1])
    expect(startX(pair[0])).not.toBe(startX(pair[1]))
  })

  it('handles an empty graph and a single block', () => {
    expect(layoutCfg({ blocks: [], edges: [], entry: null })).toEqual({ nodes: [], edges: [], width: 0, height: 0 })
    const one = { entry: 'B1', edges: [], blocks: [{ id: 1, name: 'B1', instructions: [{ text: 'print 1', index: 0 }] }] }
    const l = layoutCfg(one)
    expect(l.nodes).toHaveLength(1)
    expect(l.edges).toHaveLength(0)
  })

  it('draws a self-loop out of the bottom and back into the top, not a degenerate line', () => {
    const g = {
      entry: 'B1',
      blocks: [{ id: 1, name: 'B1', instructions: [{ text: 'x = 1', index: 0 }] }],
      edges: [{ source: 'B1', target: 'B1', kind: 'jump' }],
    }
    const l = layoutCfg(g)
    const e = l.edges[0]
    expect(e.back).toBe(true)
    expect(e.points[0].y).toBeGreaterThan(e.points[e.points.length - 1].y)
    expect(e.d).not.toContain('NaN')
    expect(l.height).toBeGreaterThan(l.nodes[0].h)       // there is room above and below the block
  })

  it('never produces NaN coordinates, for any example', () => {
    for (const r of [factorial, branches, loops]) {
      for (const g of stage(r, 'cfg').data.functions) {
        const l = layoutCfg(g)
        expect(JSON.stringify(l.edges.map((e) => e.d))).not.toMatch(/NaN|undefined/)
        expect(Number.isFinite(l.width) && Number.isFinite(l.height)).toBe(true)
      }
    }
  })
})
