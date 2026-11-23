import { useState } from 'react'
import StageGate, { Empty } from './StageGate'
import { TacListing } from './TacTab'
import { CfgViews } from './CfgTab'

const VIEWS = [
  { id: 'changes', label: 'Changes' },
  { id: 'compare', label: 'Before and after' },
  { id: 'cfg', label: 'Optimized CFG' },
]

function Changes({ data, onReveal }) {
  if (!data.changes.length) return <Empty>The optimizer found nothing to improve in this program.</Empty>
  return (
    <ol className="changes">
      {data.changes.map((c, i) => (
        <li key={i} className="change">
          <div className="change-head">
            <span className="chip">{c.pass}</span>
            <span className="muted">{c.function}{c.line ? `, ` : ''}</span>
            {c.line ? <button type="button" className="link" onClick={() => onReveal(c.line, 1)}>line {c.line}</button> : null}
          </div>
          <div className="change-diff code">
            <span className="diff-old">{c.before}</span>
            <span className="diff-arrow" aria-label="becomes">⇒</span>
            {c.after === null || c.after === undefined
              ? <span className="diff-deleted">deleted</span>
              : <span className="diff-new">{c.after}</span>}
          </div>
          <p className="muted">{c.description}</p>
        </li>
      ))}
    </ol>
  )
}

function Compare({ data, onReveal }) {
  const keep = (fn) => fn.kind === 'main' || fn.instructions.length > 0
  const after = Object.fromEntries(data.optimized.functions.map((f) => [f.name, f]))
  const removed = new Set(data.changes.map((c) => c.before))
  return (
    <div>
      {data.original.functions.filter(keep).map((fn) => (
        <div key={fn.name} className="compare">
          <div>
            <h4 className="section-title">Before</h4>
            <TacListing fn={fn} onReveal={onReveal} marked={removed} />
          </div>
          <div>
            <h4 className="section-title">After</h4>
            <TacListing fn={after[fn.name] ?? { ...fn, instructions: [] }} onReveal={onReveal} />
          </div>
        </div>
      ))}
    </div>
  )
}

export default function OptimizationTab({ tac, cfg, failedStage, onReveal }) {
  const [view, setView] = useState('changes')
  const data = tac?.data
  return (
    <StageGate stage={tac} failedStage={failedStage}>
      <p className="lede">
        The optimizer rewrites the TAC so it does the same job with less work: folding constants, removing dead
        code and unneeded temporaries. The program's output must not change, and the Output tab checks that on
        every run.
      </p>
      {data && (
        <>
          <p className="summary-line">
            <strong>{data.instruction_counts.before}</strong> instructions
            <span aria-hidden="true"> → </span><span className="sr-only"> became </span>
            <strong>{data.instruction_counts.after}</strong>
            {Object.entries(data.stats).map(([pass, n]) => (
              <span key={pass} className="chip">{pass} × {n}</span>
            ))}
          </p>
          <div className="subtabs" role="tablist" aria-label="Optimization views">
            {VIEWS.map((v) => (
              <button key={v.id} type="button" role="tab" aria-selected={view === v.id}
                      className="subtab" onClick={() => setView(v.id)}>{v.label}</button>
            ))}
          </div>
          {view === 'changes' && <Changes data={data} onReveal={onReveal} />}
          {view === 'compare' && <Compare data={data} onReveal={onReveal} />}
          {view === 'cfg' && (cfg?.data ? <CfgViews cfg={cfg.data} onReveal={onReveal} /> : <Empty>Not available.</Empty>)}
        </>
      )}
    </StageGate>
  )
}
