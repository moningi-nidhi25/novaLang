import { Empty } from './StageGate'
function explain(item) {
  const phase = String(item.phase || '').toLowerCase()
  const message = String(item.message || 'The compiler reported a problem.')
  let why = 'The compiler could not safely continue because this issue violates a language rule or prevents it from understanding the program.'
  if (phase.includes('lex') || phase.includes('token')) why = 'Lexical analysis could not classify one or more characters into valid NovaLang tokens.'
  else if (phase.includes('syntax') || phase.includes('parse') || phase.includes('ast')) why = 'The token sequence does not match the grammar expected by the parser. A missing delimiter, misplaced operator, or incomplete expression is a common cause.'
  else if (phase.includes('semantic')) why = 'The program may be grammatically valid, but a name, type, function call, or control statement does not satisfy semantic rules.'
  else if (phase.includes('runtime') || phase.includes('execution')) why = 'The program reached execution, but an operation could not be completed with the values available at runtime.'
  let suggestion = item.hint || 'Read the message and nearby source line, correct the smallest issue first, then run Analyze again.'
  if (/undefined|undeclared|not declared/i.test(message)) suggestion = 'Declare the name before using it, check its spelling and capitalization, and ensure it is in scope.'
  if (/type|operand|numeric|assign/i.test(message)) suggestion = item.hint || 'Check the types on both sides of the expression. Use compatible values or explicitly change the expression so the types match.'
  if (/expected|missing|unterminated/i.test(message)) suggestion = item.hint || 'Check the nearby line for a missing closing parenthesis, brace, quote, comma, or semicolon.'
  return { why, suggestion }
}
export default function ErrorsTab({ result, onReveal }) {
  const items = [...(result?.errors || []).map(x => ({ ...x, severity: 'error' })), ...(result?.warnings || []).map(x => ({ ...x, severity: 'warning' }))]
  return <section><p className="lede">A debugging view of compiler errors and warnings. Each item includes the compiler's message, why that class of failure usually happens, and a practical next step.</p>
    {!result ? <Empty>Press Analyze or Run to inspect your program.</Empty> : items.length === 0 ? <div><h3>No errors or warnings reported</h3><p>The latest compiler run did not report any problems. This does not guarantee every possible input or runtime path is correct.</p></div> : <>
      <h3 className="section-title">{items.length} problem{items.length === 1 ? '' : 's'} found</h3>
      {items.map((item, i) => { const detail = explain(item); return <article className="diag" data-severity={item.severity} key={`${item.phase}-${item.line}-${i}`} style={{padding: '12px', marginBottom: '12px', border: '1px solid var(--rule)', borderRadius: '6px'}}>
        <div className="diag-head"><strong>{item.severity === 'error' ? 'Error' : 'Warning'} · {item.phase || 'Compiler'}</strong><span className="diag-pos">line {item.line ?? '?'}{item.column ? `, column ${item.column}` : ''}</span></div>
        <p><b>Compiler message:</b> {item.message}</p><p><b>Why it happened:</b> {detail.why}</p><p><b>Suggested fix:</b> {detail.suggestion}</p>
        {item.line && <button type="button" className="btn small" onClick={() => onReveal(item.line, item.column || 1)}>Go to source line</button>}
      </article>})}</>}
  </section>
}
