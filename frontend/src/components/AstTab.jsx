import { useState } from 'react'
import StageGate from './StageGate'
import AstGraph from './AstGraph'
import { splitFields } from '../lib/astFields'

export { isNode, splitFields } from '../lib/astFields'

function Node({ node, field, depth, mode, onReveal }) {
  const { props, children } = splitFields(node)
  const expandable = children.length > 0
  const initial = mode === 'all' ? true : mode === 'none' ? depth === 0 : depth < 3
  const [open, setOpen] = useState(initial)

  return (
    <li className="ast-node">
      <div className="ast-row">
        {expandable ? (
          <button type="button" className="twisty" aria-expanded={open}
                  aria-label={`${open ? 'Collapse' : 'Expand'} ${node.type}`} onClick={() => setOpen(!open)}>
            {open ? '▾' : '▸'}
          </button>
        ) : <span className="twisty-gap" />}
        {field && <span className="ast-field">{field}</span>}
        <button type="button" className="ast-main" onClick={() => onReveal(node.line, node.column)}
                title={`Go to line ${node.line}`}>
          <span className="ast-type">{node.type}</span>
          {node.label ? <span className="ast-label code">{node.label}</span> : null}
        </button>
        {props.map(([k, v]) => (
          k !== 'name' && k !== 'operator' && k !== 'value' ? <span key={k} className="ast-prop">{k}={v}</span> : null
        ))}
        {node.inferred_type && <span className="chip type-chip" title="Type found by semantic analysis">{node.inferred_type}</span>}
      </div>
      {expandable && open && (
        <ul className="ast-children">
          {children.map(([key, list]) => list.map((child, i) => (
            <Node key={`${key}${i}`} node={child} field={list.length > 1 ? `${key}[${i}]` : key}
                  depth={depth + 1} mode={mode} onReveal={onReveal} />
          )))}
        </ul>
      )}
    </li>
  )
}

export default function AstTab({ stage, failedStage, onReveal }) {
  const [mode, setMode] = useState({ kind: 'default', n: 0 })
  const [view, setView] = useState('graph')
  return (
    <StageGate stage={stage} failedStage={failedStage}>
      <p className="lede">
        The parser turns the tokens into a tree that mirrors the program's structure. Chips show the types the
        semantic analyzer worked out. Click a node to jump to its source.
      </p>
      <div className="subtabs" role="tablist" aria-label="Syntax tree views">
        <button type="button" role="tab" className="subtab" aria-selected={view === 'graph'}
                onClick={() => setView('graph')}>Diagram</button>
        <button type="button" role="tab" className="subtab" aria-selected={view === 'outline'}
                onClick={() => setView('outline')}>Outline</button>
      </div>
      {stage?.data && view === 'graph' && <AstGraph root={stage.data} onReveal={onReveal} />}
      {view === 'outline' && (
      <div className="toolbar">
        <button type="button" className="btn small" onClick={() => setMode({ kind: 'all', n: mode.n + 1 })}>Expand all</button>
        <button type="button" className="btn small" onClick={() => setMode({ kind: 'none', n: mode.n + 1 })}>Collapse all</button>
      </div>
      )}
      {stage?.data && view === 'outline' && (
        <ul className="ast-tree" role="tree" key={mode.n}>
          <Node node={stage.data} depth={0} mode={mode.kind} onReveal={onReveal} />
        </ul>
      )}
    </StageGate>
  )
}
