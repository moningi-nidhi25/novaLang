import { useMemo, useState } from 'react'
import GraphCanvas from './GraphCanvas'
import { CFG, instructionText, layoutCfg } from '../lib/graphLayout'
import { EDGE_TEXT } from '../lib/edges'

const markerKind = (e, hot) => (hot ? 'hot' : e.kind === 'true' ? 'true' : e.kind === 'false' ? 'false' : 'plain')

/** One function's control-flow graph: blocks as boxes, jumps as arrows, loops curving down the right side. */
function FunctionGraph({ graph, onReveal }) {
  const layout = useMemo(() => layoutCfg(graph), [graph])
  const [selected, setSelected] = useState(null)
  const byName = useMemo(() => new Map(layout.nodes.map((n) => [n.name, n])), [layout])
  const current = selected && byName.get(selected)
  const touches = (e) => current && (e.source === selected || e.target === selected)
  const incident = new Set(layout.edges.filter(touches).flatMap((e) => [e.source, e.target]))
  const outgoing = current ? layout.edges.filter((e) => e.source === selected) : []
  const incoming = current ? layout.edges.filter((e) => e.target === selected) : []

  const keyActivate = (fn) => (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); fn() }
  }

  if (layout.nodes.length === 0) return <p className="muted">(no instructions)</p>
  return (
    <div className="graph-wrap">
      <GraphCanvas width={layout.width} height={layout.height} label={`Control-flow graph of ${graph.function}`}
                   fitKey={`${graph.function}:${layout.nodes.length}`}>
        {(mid) => (
          <>
            <g className="gedges">
              {layout.edges.map((e, i) => {
                const hot = touches(e)
                return (
                  <g key={i} data-kind={e.kind} data-back={e.back || undefined} data-hot={hot || undefined}
                     data-dim={(current && !hot) || undefined}>
                    <path className="gedge cfg-edge" d={e.d} markerEnd={`url(#${mid}-${markerKind(e, hot && e.kind !== 'true' && e.kind !== 'false')})`} />
                    {(e.kind === 'true' || e.kind === 'false') && (
                      <text className="gedge-label" x={e.label.x} y={e.label.y}>{e.kind}</text>
                    )}
                  </g>
                )
              })}
            </g>
            <g className="gnodes">
              {layout.nodes.map((n) => {
                const b = n.block
                const entry = b.name === graph.entry
                const tag = !b.reachable ? 'unreachable' : entry ? 'entry' : b.is_exit ? 'exit' : ''
                return (
                  <g key={n.name} className="gblock" transform={`translate(${n.x} ${n.y})`}
                     data-selected={n.name === selected || undefined}
                     data-linked={(current && incident.has(n.name) && n.name !== selected) || undefined}
                     data-unreachable={!b.reachable || undefined}
                     data-dim={(current && !incident.has(n.name)) || undefined}>
                    <rect className="gblock-box" width={n.w} height={n.h} rx="7" />
                    <g role="button" tabIndex={0} aria-pressed={n.name === selected}
                       aria-label={`Block ${b.name}${tag ? `, ${tag}` : ''}`}
                       onClick={() => setSelected(n.name === selected ? null : n.name)}
                       onKeyDown={keyActivate(() => setSelected(n.name === selected ? null : n.name))}>
                      <rect className="gblock-head" width={n.w} height={CFG.head} rx="7" />
                      <text className="gb-name" x={CFG.padX} y={17}>{b.name}</text>
                      {tag && <text className="gb-tag" x={n.w - CFG.padX} y={17} textAnchor="end">{tag}</text>}
                    </g>
                    {b.instructions.map((ins, i) => (
                      <g key={ins.index} className="gline" data-label={ins.op === 'label' || undefined}
                         transform={`translate(0 ${CFG.head + i * CFG.line})`}
                         role={ins.line ? 'button' : undefined} tabIndex={ins.line ? 0 : undefined}
                         aria-label={ins.line ? `${ins.text}, source line ${ins.line}` : undefined}
                         onClick={() => ins.line && onReveal?.(ins.line, ins.column)}
                         onKeyDown={ins.line ? keyActivate(() => onReveal?.(ins.line, ins.column)) : undefined}>
                        <title>{ins.text}</title>
                        <rect className="gline-hit" width={n.w} height={CFG.line} />
                        <text className="gl-index" x={CFG.padX} y={14}>{ins.index}</text>
                        <text className="gl-text" x={CFG.padX + 30} y={14}>{instructionText(ins)}</text>
                      </g>
                    ))}
                  </g>
                )
              })}
            </g>
          </>
        )}
      </GraphCanvas>
      <div className="graph-detail" aria-live="polite">
        {current ? (
          <>
            <strong>{current.name}</strong>
            <span className="muted"> {current.block.leader_reasons.join('; ')}</span>
            {!current.block.reachable && <span className="chip warn-chip">unreachable</span>}
            <p className="muted">
              {outgoing.length === 0
                ? 'The function ends here.'
                : outgoing.map((e, i) => (
                  <span key={i}>{i > 0 ? '; ' : ''}{EDGE_TEXT[e.kind] ?? e.kind} <strong>{e.target}</strong></span>
                ))}
              {incoming.length > 0 && ` Reached from ${[...new Set(incoming.map((e) => e.source))].join(', ')}.`}
            </p>
          </>
        ) : (
          <span className="muted">
            Select a block to highlight the arrows in and out of it. Click an instruction to jump to its source.
            Green and red arrows are the two outcomes of a condition; a curve on the right is a loop going back up.
          </span>
        )}
      </div>
    </div>
  )
}

/** All functions of a program; a picker appears when there is more than one. */
export default function CfgGraph({ cfg, onReveal }) {
  const [name, setName] = useState(cfg.functions[0]?.function)
  const graph = cfg.functions.find((g) => g.function === name) ?? cfg.functions[0]
  if (!graph) return null
  return (
    <div>
      {cfg.functions.length > 1 && (
        <div className="subtabs" role="tablist" aria-label="Function">
          {cfg.functions.map((g) => (
            <button key={g.function} type="button" role="tab" className="subtab"
                    aria-selected={g.function === graph.function} onClick={() => setName(g.function)}>
              {g.function === 'main' ? 'main' : g.function}
            </button>
          ))}
        </div>
      )}
      <FunctionGraph key={graph.function} graph={graph} onReveal={onReveal} />
    </div>
  )
}
