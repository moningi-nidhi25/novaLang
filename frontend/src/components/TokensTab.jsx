import StageGate from './StageGate'

const show = (lexeme) => (lexeme === '' ? '(end of file)' : lexeme.replace(/\n/g, '\\n'))

export default function TokensTab({ stage, failedStage, onReveal }) {
  return (
    <StageGate stage={stage} failedStage={failedStage} allowError>
      <p className="lede">
        The lexer reads characters and groups them into tokens, the smallest meaningful pieces of the program.
      </p>
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr><th>#</th><th>Type</th><th>Lexeme</th><th>Value</th><th>Position</th></tr>
          </thead>
          <tbody>
            {(stage?.data ?? []).map((t, i) => (
              <tr key={i} className="clickable" onClick={() => onReveal(t.line, t.column)}>
                <td className="num">{i + 1}</td>
                <td><span className="chip">{t.type}</span></td>
                <td className="code">{show(t.lexeme)}</td>
                <td className="code">{t.value === null || t.value === undefined ? '' : JSON.stringify(t.value)}</td>
                <td className="num">{t.line}:{t.column}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </StageGate>
  )
}
