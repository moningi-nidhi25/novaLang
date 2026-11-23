import { stageLabel } from '../lib/stages'

/**
 * Wraps a tab's content and explains the three "nothing to show" cases:
 * the stage was never requested, it was skipped after a failure, or it failed itself.
 */
export default function StageGate({ stage, failedStage, children, allowError = false }) {
  if (!stage) {
    return <Empty>Press <b>Run</b> to see this stage.</Empty>
  }
  if (stage.status === 'skipped') {
    return (
      <Empty>
        Skipped: the compiler stopped at <b>{stageLabel(failedStage)}</b>. Fix the problem
        listed on the left and run again.
      </Empty>
    )
  }
  if (stage.status === 'error' && !allowError) {
    return (
      <Empty>
        This stage found errors, so it produced nothing to show. See <b>Problems</b> on the left.
      </Empty>
    )
  }
  return children
}

export function Empty({ children }) {
  return <p className="empty">{children}</p>
}
