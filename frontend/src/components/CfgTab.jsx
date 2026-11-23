import { useState } from 'react'
import StageGate from './StageGate'
import CfgGraph from './CfgGraph'
import { EDGE_TEXT } from '../lib/edges'

/** All functions' control-flow graphs as readable block cards (the text view). */
export function CfgView({ cfg, onReveal }) {
  return (
    <div className="cfg">
      {cfg.functions.map((g) => (
        <section key={g.function} className="cfg-fn">
          <h3 className="section-title">{g.function === 'main' ? 'main' : `function ${g.function}`}</h3>
          {g.blocks.length === 0 && <p className="muted">(no instructions)</p>}
          {g.blocks.map((b) => {
            const out = g.edges.filter((e) => e.source === b.name)
            return (
              <article key={b.name} className="block" data-unreachable={!b.reachable || undefined}>
                <header className="block-head">
                  <strong>{b.name}</strong>
                  <span className="muted">{b.leader_reasons.join('; ')}</span>
                  {b.is_entry && <span className="chip">entry</span>}
                  {b.is_exit && <span className="chip">exit</span>}
                  {!b.reachable && <span className="chip warn-chip">unreachable</span>}
                </header>
                <div className="block-body">
                  {b.instructions.map((ins) => (
                    <button type="button" key={ins.index} className="listing-row code"
                            data-label={ins.op === 'label'} disabled={!ins.line}
                            onClick={() => onReveal?.(ins.line, ins.column)}>
                      <span className="listing-index">{ins.index}</span>
                      <span className="listing-text">{ins.text}</span>
                    </button>
                  ))}
                </div>
                <footer className="block-foot">
                  {out.length === 0
                    ? <span className="muted">The function ends here.</span>
                    : out.map((e, i) => (
                      <span key={i}>{EDGE_TEXT[e.kind] ?? e.kind} <strong>{e.target}</strong></span>
                    ))}
                </footer>
              </article>
            )
          })}
        </section>
      ))}
    </div>
  )
}

/** The drawn graph by default, with the plain block cards one click away. */
export function CfgViews({ cfg, onReveal }) {
  const [view, setView] = useState('graph')
  return (
    <>
      <div className="subtabs" role="tablist" aria-label="Control-flow graph views">
        <button type="button" role="tab" className="subtab" aria-selected={view === 'graph'}
                onClick={() => setView('graph')}>Diagram</button>
        <button type="button" role="tab" className="subtab" aria-selected={view === 'blocks'}
                onClick={() => setView('blocks')}>Blocks</button>
      </div>
      {view === 'graph' ? <CfgGraph cfg={cfg} onReveal={onReveal} /> : <CfgView cfg={cfg} onReveal={onReveal} />}
    </>
  )
}

export default function CfgTab({ stage, failedStage, onReveal }) {
  return (
    <StageGate stage={stage} failedStage={failedStage}>
      <p className="lede">
        A basic block is a run of instructions with one way in and one way out. Blocks joined by the jumps
        between them form the control-flow graph, the map the optimizer reads.
      </p>
      {stage?.data && <CfgViews cfg={stage.data} onReveal={onReveal} />}
    </StageGate>
  )
}
