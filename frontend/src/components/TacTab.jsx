import { useState } from 'react'
import StageGate from './StageGate'

const JUMPS = new Set(['goto', 'if_false', 'if_true'])

/** One function's instructions. Labels sit at the left edge, instructions are indented. */
export function TacListing({ fn, onReveal, marked }) {
  // Selecting a jump lights up its target label; selecting a label lights up every jump to it.
  const [picked, setPicked] = useState(null)
  const pickedIns = fn.instructions.find((i) => i.index === picked)
  const target = pickedIns && (JUMPS.has(pickedIns.op) ? pickedIns.result : pickedIns.op === 'label' ? pickedIns.result : null)
  const related = (ins) => target != null && ins.index !== picked && (
    (ins.op === 'label' && ins.result === target) || (JUMPS.has(ins.op) && ins.result === target))
  const header = fn.kind === 'main' ? 'main:' : `function ${fn.name}(${fn.params.join(', ')}):`
  return (
    <div className="listing">
      <div className="listing-head code">{header}</div>
      {fn.instructions.length === 0 && <div className="listing-row muted">(no instructions)</div>}
      {fn.instructions.map((ins) => (
        <button
          type="button"
          key={ins.index}
          className="listing-row code"
          data-label={ins.op === 'label'}
          data-marked={marked?.has(ins.text) ? 'true' : undefined}
          data-related={related(ins) || undefined}
          data-picked={ins.index === picked || undefined}
          onClick={() => { setPicked(ins.index === picked ? null : ins.index); if (ins.line) onReveal?.(ins.line, ins.column) }}
          title={JUMPS.has(ins.op) ? `Jumps to ${ins.result}` : ins.line ? `Source line ${ins.line}` : undefined}
        >
          <span className="listing-index">{ins.index}</span>
          <span className="listing-text">{ins.text}</span>
        </button>
      ))}
    </div>
  )
}

export default function TacTab({ stage, failedStage, onReveal }) {
  const tac = stage?.data
  return (
    <StageGate stage={stage} failedStage={failedStage}>
      <p className="lede">
        Three Address Code is a flat list of tiny steps, each with at most one operation. Temporaries
        (<code>t1</code>, <code>t2</code>) hold intermediate results and labels (<code>L1</code>) mark jump targets.
        Click a line to see where it came from.
      </p>
      {tac?.globals?.length > 0 && (
        <p className="muted">Global variables: <span className="code">{tac.globals.join(', ')}</span></p>
      )}
      {tac?.functions.map((fn) => (fn.instructions.length > 0 || fn.kind === 'main') && (
        <TacListing key={fn.name} fn={fn} onReveal={onReveal} />
      ))}
    </StageGate>
  )
}
