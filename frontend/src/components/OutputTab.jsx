import StageGate from './StageGate'

export default function OutputTab({ stage, failedStage }) {
  const data = stage?.data
  const failed = stage?.status === 'error'
  return (
    <StageGate stage={stage} failedStage={failedStage} allowError>
      {data && (
        <>
          <h3 className="section-title">Program output</h3>
          <pre className="console" aria-label="Program output">
            {data.output || <span className="muted">(the program printed nothing)</span>}
          </pre>

          {failed
            ? <p className="verdict bad">The program stopped with a run-time error. See Problems on the left.</p>
            : <p className="muted">Finished in {data.steps} steps.</p>}

          <p className={`verdict ${data.verified ? 'good' : 'bad'}`}>
            {data.verified
              ? 'Verified: the optimized TAC behaves exactly like the original program.'
              : 'Mismatch: the optimized TAC behaves differently. This is a compiler bug.'}
          </p>

          {Object.keys(data.variables).length > 0 && (
            <>
              <h3 className="section-title">Variables at the end</h3>
              <table className="grid">
                <thead><tr><th>Name</th><th>Value</th></tr></thead>
                <tbody>
                  {Object.entries(data.variables).map(([k, v]) => (
                    <tr key={k}><td className="code">{k}</td><td className="code">{v}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </StageGate>
  )
}
