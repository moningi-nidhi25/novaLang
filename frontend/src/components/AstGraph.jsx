import { useMemo, useState } from 'react'
import GraphCanvas from './GraphCanvas'
import { splitFields } from './AstTab'
import { astKind, layoutTree, pathTo, shorten } from '../lib/graphLayout'

/** [[field, child], ...] in source order; list children are named name[0], name[1]... */
export function childrenOf(node) {
  return splitFields(node).children.flatMap(([key, list]) =>
    list.map((child, i) => [list.length > 1 ? `${key}[${i}]` : key, child]))
}

const curve = (a, b) => {
  const x1 = a.x + a.w / 2
  const y1 = a.y + a.h
  const x2 = b.x + b.w / 2
  const y2 = b.y
  const dy = (y2 - y1) / 2
  return `M ${x1} ${y1} C ${x1} ${y1 + dy} ${x2} ${y2 - dy} ${x2} ${y2}`
}

/** The syntax tree drawn as a diagram. Click a node: highlight its path to the root and jump to its source. */
export default function AstGraph({ root, onReveal }) {
  const [collapsed, setCollapsed] = useState(() => new Set())
  const [selectedId, setSelectedId] = useState(null)
  const layout = useMemo(() => layoutTree(root, childrenOf, { collapsed }), [root, collapsed])
  const byId = useMemo(() => new Map(layout.nodes.map((n) => [n.id, n])), [layout])

  const selected = selectedId && byId.get(selectedId)
  const onPath = new Set(selected ? pathTo(selected.id) : [])

  const select = (n) => {
    setSelectedId(n.id)
    onReveal?.(n.node.line, n.node.column)
  }
  const toggle = (n) => setCollapsed((prev) => {
    const next = new Set(prev)
    if (next.has(n.id)) next.delete(n.id)
    else next.add(n.id)
    return next
  })
  const keyActivate = (fn) => (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); fn() }
  }

  const detail = selected && splitFields(selected.node)
  const hiddenCount = collapsed.size

  return (
    <div className="graph-wrap">
      <GraphCanvas width={layout.width} height={layout.height} label="Syntax tree diagram"
                   fitKey={`${layout.nodes.length}`}>
        {() => (
          <>
            <g className="gedges">
              {layout.edges.map((e) => (
                <path key={e.to} className="gedge" d={curve(byId.get(e.from), byId.get(e.to))}
                      data-onpath={onPath.has(e.to) || undefined} />
              ))}
            </g>
            <g className="gnodes">
              {layout.nodes.map((n) => {
                const name = n.node.label ? `${n.node.type} ${n.node.label}` : n.node.type
                return (
                  <g key={n.id} className="gnode" transform={`translate(${n.x} ${n.y})`}
                     data-kind={astKind(n.node.type)} data-selected={n.id === selectedId || undefined}
                     data-onpath={onPath.has(n.id) || undefined}
                     role="button" tabIndex={0} aria-pressed={n.id === selectedId}
                     aria-label={`${name}, line ${n.node.line}`}
                     onClick={() => select(n)} onKeyDown={keyActivate(() => select(n))}>
                    <title>{`${name} (line ${n.node.line})`}</title>
                    <rect width={n.w} height={n.h} rx="9" />
                    <text className="gt-type" x={n.w / 2} y={n.node.label ? 19 : 28} textAnchor="middle">{n.node.type}</text>
                    {n.node.label ? (
                      <text className="gt-label" x={n.w / 2} y={36} textAnchor="middle">{shorten(n.node.label, 18)}</text>
                    ) : null}
                  </g>
                )
              })}
            </g>
            <g className="gtoggles">
              {layout.nodes.filter((n) => n.hasChildren).map((n) => (
                <g key={n.id} className="gtoggle" transform={`translate(${n.x + n.w / 2} ${n.y + n.h})`}
                   role="button" tabIndex={0} aria-label={`${n.collapsed ? 'Expand' : 'Collapse'} ${n.node.type} subtree`}
                   onClick={(e) => { e.stopPropagation(); toggle(n) }} onKeyDown={keyActivate(() => toggle(n))}>
                  <circle r="9" />
                  <text textAnchor="middle" y="4">{n.collapsed ? '+' : '−'}</text>
                </g>
              ))}
            </g>
          </>
        )}
      </GraphCanvas>
      <div className="graph-detail" aria-live="polite">
        {selected ? (
          <>
            <strong>{selected.node.type}</strong>
            {selected.node.label ? <span className="code"> {selected.node.label}</span> : null}
            <span className="muted"> at line {selected.node.line}, column {selected.node.column}</span>
            {selected.node.inferred_type && <span className="chip type-chip" title="Type found by semantic analysis">{selected.node.inferred_type}</span>}
            {selected.field && <p className="muted">It is the <span className="code">{selected.field}</span> of its parent. Highlighted: the path up to the program root.</p>}
            {detail.props.length > 0 && (
              <p className="muted">{detail.props.map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
            )}
          </>
        ) : (
          <span className="muted">
            Select a node to highlight its path to the root and jump to its source.
            {hiddenCount > 0 ? ` ${hiddenCount} subtree${hiddenCount > 1 ? 's' : ''} collapsed.` : ' Use the round buttons to collapse a subtree.'}
          </span>
        )}
      </div>
    </div>
  )
}
