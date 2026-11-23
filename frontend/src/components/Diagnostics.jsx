/** Flatten the response's errors and warnings into one list the editor and panel share. */
export function collectDiagnostics(result) {
  if (!result) return []
  const tag = (list, severity) => (list ?? []).map((d) => ({ ...d, severity }))
  return [...tag(result.errors, 'error'), ...tag(result.warnings, 'warning')]
}

/** Errors and warnings with their hints. Clicking one jumps to the source line. */
export default function Diagnostics({ items, onReveal }) {
  if (!items.length) return null
  return (
    <section className="diagnostics" aria-label="Problems">
      <h2 className="panel-title">
        Problems <span className="count">{items.length}</span>
      </h2>
      <ul>
        {items.map((d, i) => (
          <li key={i} className="diag" data-severity={d.severity}>
            <button type="button" onClick={() => onReveal(d.line, d.column)}>
              <span className="diag-head">
                <span className="diag-phase">{d.phase}</span>
                <span className="diag-pos">line {d.line}, column {d.column}</span>
              </span>
              <span className="diag-msg">{d.message}</span>
              {d.hint && <span className="diag-hint">{d.hint}</span>}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
