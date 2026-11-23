import { STAGES, stageMap, statusOf, tabForStage } from '../lib/stages'

const STATUS_TEXT = {
  ok: 'finished',
  warning: 'finished with warnings',
  error: 'found errors',
  skipped: 'skipped because an earlier stage failed',
  idle: 'not run yet',
}

/**
 * The pipeline as a horizontal line of stages. It shows where the compiler
 * is, and, when something fails, exactly which stage stopped it.
 */
export default function StageRail({ result, activeTab, onSelect }) {
  const map = stageMap(result)
  const failed = result?.failed_stage

  return (
    <nav className="rail" aria-label="Compiler pipeline">
      <ol className="rail-steps">
        {STAGES.map((stage, i) => {
          const status = statusOf(map, stage.id)
          const tab = tabForStage(stage.id)
          const summary = map[stage.id]?.summary
          const current = tab && tab === activeTab
          return (
            <li key={stage.id} className="rail-step" data-status={status}>
              {i > 0 && <span className="rail-link" aria-hidden="true" data-from={statusOf(map, STAGES[i - 1].id)} />}
              <button
                type="button"
                className="rail-node"
                data-status={status}
                aria-current={current ? 'step' : undefined}
                disabled={!tab}
                onClick={() => tab && onSelect(tab)}
                title={`${stage.label}: ${summary || STATUS_TEXT[status]}`}
              >
                <span className="rail-dot" aria-hidden="true" />
                <span className="rail-label">{stage.label}</span>
                <span className="sr-only"> {STATUS_TEXT[status]}</span>
              </button>
            </li>
          )
        })}
      </ol>
      {failed && (
        <p className="rail-note" role="status">
          The compiler stopped at <strong>{STAGES.find((s) => s.id === failed)?.label ?? failed}</strong>.
          Later stages did not run.
        </p>
      )}
    </nav>
  )
}
