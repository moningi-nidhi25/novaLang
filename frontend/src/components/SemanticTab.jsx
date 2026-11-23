import StageGate, { Empty } from './StageGate'

export const hasSymbols = (scope) => scope.symbols.length > 0 || scope.children.some(hasSymbols)

function Scope({ scope, onReveal }) {
  return (
    <div className="scope" style={{ '--depth': scope.level }}>
      <h4 className="scope-name">{scope.name} <span className="muted">{scope.kind || 'scope'} · level {scope.level}</span></h4>
      {scope.symbols.length > 0 && <div className="table-wrap"><table className="grid">
        <thead><tr><th>Name</th><th>Kind / role</th><th>Type</th><th>Scope</th><th>Declared at</th><th>Meaning</th></tr></thead>
        <tbody>{scope.symbols.map((s) => <tr key={`${s.name}-${s.line}`} className="clickable" onClick={() => s.line && onReveal(s.line, s.column)}>
          <td className="code">{s.params ? `${s.name}(${s.params.join(', ')})` : s.name}</td><td>{s.kind}</td>
          <td><span className="chip type-chip">{s.type}</span></td><td>{s.scope || scope.name}</td>
          <td className="num">{s.line ? `${s.line}:${s.column}` : 'built-in'}</td>
          <td>{symbolMeaning(s)}</td>
        </tr>)}</tbody>
      </table></div>}
      {scope.children.map((c, i) => <Scope key={`${c.name}-${i}`} scope={c} onReveal={onReveal} />)}
    </div>
  )
}
function symbolMeaning(s) {
  if (s.kind === 'function' || s.kind === 'builtin') return `Callable function; parameters: ${(s.params || []).join(', ') || 'not listed'}.`
  if (s.kind === 'parameter') return 'Input value received by its function; its value is available inside that function scope.'
  return `A ${s.type} name declared here; it can be looked up within this scope and its nested scopes.`
}
function lineMeaning(line) {
  const t = line.trim()
  if (!t) return 'Blank line; ignored by the compiler.'
  if (t.startsWith('//') || t.startsWith('/*') || t.startsWith('*')) return 'Comment text; documents the program and is not executed.'
  if (/^function\b/.test(t)) return 'Function declaration: introduces a reusable named block and its parameters.'
  if (/^let\b/.test(t)) return 'Variable declaration: creates a name and initializes it with the expression on the right.'
  if (/^if\b/.test(t)) return 'Conditional statement: evaluates a condition and selects which block can execute.'
  if (/^else\b/.test(t)) return 'Alternative branch: runs when the preceding if condition is false.'
  if (/^while\b|^for\b/.test(t)) return 'Loop statement: repeats a block according to its condition or iteration rule.'
  if (/^return\b/.test(t)) return 'Return statement: exits the current function and optionally sends a value to the caller.'
  if (/^print\s*\(/.test(t)) return 'Output call: evaluates its argument and displays the resulting value.'
  if (t === '{' || t.includes('{')) return 'Opening block: creates a nested region of code; declarations may belong to this scope.'
  if (t === '}' || t.includes('}')) return 'Closing block: ends the current block and its local scope.'
  if (t.includes('?') && t.includes(':')) return 'Ternary-shaped expression: condition ? value_if_true : value_if_false. Both branches should produce compatible values; parser support depends on the compiler grammar.'
  if (t.includes('=')) return 'Assignment or initialization: computes the right-hand expression and stores it in the target name.'
  if (/[+*/%<>!]=?|&&|\|\|/.test(t)) return 'Expression: operators combine values; semantic analysis checks whether operand types are compatible.'
  if (t.endsWith(';')) return 'Statement terminator: marks the end of this statement.'
  return 'Statement or expression: the compiler interprets the tokens according to the language grammar.'
}
export default function SemanticTab({ semantic, symbols, failedStage, onReveal, source = '' }) {
  const lines = source.split('\n')
  return <StageGate stage={semantic} failedStage={failedStage} allowError>
    <p className="lede">Semantic analysis checks whether a syntactically valid program makes sense: names must be declared, types must be compatible, calls must use valid arguments, and control statements must appear in valid locations.</p>
    <h3 className="section-title">How to read the symbol table</h3>
    <p>Each row is a declared name. <b>Name</b> is the identifier, <b>kind</b> says whether it is a variable, parameter, function or built-in, <b>type</b> is the inferred/declared static type, <b>scope</b> tells where it belongs, and <b>declared at</b> is its source position. Click a row to jump to its declaration. Nested scopes are shown underneath their parent.</p>
    <h3 className="section-title">Complete symbol table and scope tree</h3>
    {symbols?.data ? <Scope scope={symbols.data} onReveal={onReveal} /> : <Empty>No symbol table is available yet. Run Analyze or Run first.</Empty>}
    <h3 className="section-title">Semantic analyzer messages</h3>
    {semantic?.data?.info?.length ? <ul className="plain-list">{semantic.data.info.map((m, i) => <li key={i}><button type="button" className="link" onClick={() => onReveal(m.line, m.column)}>line {m.line}:{m.column}</button> — {m.message}</li>)}</ul> : <Empty>No semantic notes were returned for this run.</Empty>}
    <h3 className="section-title">Line-by-line program explanation</h3>
    <p>These explanations describe the likely role of each source line. The compiler's semantic messages and symbol table above are the authoritative analysis; this guide is a readable learning aid.</p>
    <div className="table-wrap"><table className="grid"><thead><tr><th>Line</th><th>Source</th><th>Explanation</th></tr></thead><tbody>{lines.map((line, i) => <tr key={i} className="clickable" onClick={() => onReveal(i + 1, 1)}><td className="num">{i + 1}</td><td className="code">{line || ' '}</td><td>{lineMeaning(line)}</td></tr>)}</tbody></table></div>
  </StageGate>
}
