import { render, screen, within, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  analyzeOnly, branches, factorial, lexError, optimizing, runtimeError, semanticError, stage, syntaxError,
} from './fixtures'
import { STAGES, TABS, stageMap, statusOf, tabForStage, worstStatus } from '../lib/stages'
import StageRail from '../components/StageRail'
import Inspector from '../components/Inspector'
import Diagnostics, { collectDiagnostics } from '../components/Diagnostics'
import AstTab, { isNode, splitFields } from '../components/AstTab'
import { hasSymbols } from '../components/SemanticTab'

const noop = () => {}

describe('stage helpers', () => {
  it('has the ten stages the backend reports, in order', () => {
    expect(STAGES.map((s) => s.id)).toEqual(factorial.stages.map((s) => s.id))
    expect(STAGES).toHaveLength(10)
  })
  it('every stage except source belongs to a tab', () => {
    for (const s of STAGES) expect(tabForStage(s.id) !== null).toBe(s.id !== 'source')
    expect(TABS.flatMap((t) => t.stages).sort()).toEqual(STAGES.map((s) => s.id).filter((i) => i !== 'source').sort())
  })
  it('statusOf distinguishes idle (not requested) from skipped', () => {
    const map = stageMap(analyzeOnly)
    expect(statusOf(map, 'tokens')).toBe('ok')
    expect(statusOf(map, 'tac')).toBe('idle')
    expect(statusOf(stageMap(syntaxError), 'tac')).toBe('skipped')
  })
  it('worstStatus picks error over warning over ok', () => {
    const map = stageMap(semanticError)
    expect(worstStatus(map, ['semantic', 'symbol_table'])).toBe('error')
    expect(worstStatus({}, ['tokens'])).toBe('idle')
  })
})

describe('StageRail', () => {
  it('lists all stages as idle before anything runs', () => {
    render(<StageRail result={null} activeTab="tokens" onSelect={noop} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(10)
    expect(screen.queryByRole('status')).toBeNull()
  })
  it('shows a successful run with no failure note', () => {
    render(<StageRail result={factorial} activeTab="output" onSelect={noop} />)
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByRole('button', { name: /Tokens finished/ })).toBeInTheDocument()
  })
  it('names the stage that stopped the compiler', () => {
    render(<StageRail result={syntaxError} activeTab="ast" onSelect={noop} />)
    expect(screen.getByRole('status')).toHaveTextContent('stopped at Syntax tree')
    expect(screen.getByRole('button', { name: /Syntax tree found errors/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^TAC skipped/ })).toBeInTheDocument()
  })
  it('selecting a stage opens its tab; Symbols opens the Semantic tab', () => {
    const onSelect = vi.fn()
    render(<StageRail result={factorial} activeTab="tokens" onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /^Symbols/ }))
    expect(onSelect).toHaveBeenCalledWith('semantic')
    fireEvent.click(screen.getByRole('button', { name: /^Run/ }))
    expect(onSelect).toHaveBeenCalledWith('output')
  })
  it('the source stage is not clickable (it has no tab)', () => {
    render(<StageRail result={factorial} activeTab="tokens" onSelect={noop} />)
    expect(screen.getByRole('button', { name: /^Source/ })).toBeDisabled()
  })
  it('marks the current tab', () => {
    render(<StageRail result={factorial} activeTab="tac" onSelect={noop} />)
    expect(screen.getByRole('button', { name: /^TAC/ })).toHaveAttribute('aria-current', 'step')
  })
})

describe('Diagnostics', () => {
  it('collects errors then warnings with severity', () => {
    const items = collectDiagnostics(semanticError)
    expect(items[0]).toMatchObject({ severity: 'error', phase: 'Semantic Error', line: 1 })
    expect(collectDiagnostics(null)).toEqual([])
  })
  it('renders nothing when there are no problems', () => {
    const { container } = render(<Diagnostics items={[]} onReveal={noop} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('shows message, hint and position, and jumps to source on click', () => {
    const onReveal = vi.fn()
    render(<Diagnostics items={collectDiagnostics(semanticError)} onReveal={onReveal} />)
    expect(screen.getByText(/'zzz' is not defined/)).toBeInTheDocument()
    expect(screen.getByText(/Declare it before use/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /not defined/ }))
    expect(onReveal).toHaveBeenCalledWith(1, 7)
  })
  it('includes warnings', () => {
    const items = collectDiagnostics(runtimeError)
    expect(items.some((d) => d.severity === 'error' && d.phase === 'Runtime Error')).toBe(true)
  })
})

describe('AST helpers', () => {
  const ast = stage(factorial, 'ast').data
  it('recognises nodes', () => {
    expect(isNode(ast)).toBe(true)
    expect(isNode({ type: 'x' })).toBe(false)
    expect(isNode(null)).toBe(false)
    expect(isNode([ast])).toBe(false)
  })
  it('splits a node into properties and child nodes', () => {
    const fn = ast.body[0]
    const { props, children } = splitFields(fn)
    expect(props.find(([k]) => k === 'name')[1]).toBe('factorial')
    expect(props.find(([k]) => k === 'params')[1]).toBe('n')
    expect(children.map(([k]) => k)).toEqual(['body'])
  })
  it('lists children of a program as one group of nodes', () => {
    const { children } = splitFields(ast)
    expect(children[0][0]).toBe('body')
    expect(children[0][1]).toHaveLength(3)
  })
})

describe('AstTab', () => {
  it('renders the tree and reveals source on click', () => {
    const onReveal = vi.fn()
    render(<AstTab stage={stage(factorial, 'ast')} failedStage={null} onReveal={onReveal} />)
    expect(screen.getByText('FunctionDeclaration')).toBeInTheDocument()
    fireEvent.click(screen.getByText('FunctionDeclaration'))
    expect(onReveal).toHaveBeenCalledWith(1, 1)
  })
  it('expand all reveals deep nodes; collapse all hides them again', () => {
    render(<AstTab stage={stage(factorial, 'ast')} failedStage={null} onReveal={noop} />)
    fireEvent.click(screen.getByRole('tab', { name: 'Outline' }))   // the diagram is the default view
    expect(screen.queryByText('BinaryExpression')).toBeNull()      // depth 4: hidden by default
    fireEvent.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.getAllByText('BinaryExpression').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Collapse all' }))
    expect(screen.queryByText('BinaryExpression')).toBeNull()
    expect(screen.queryByText('FunctionDeclaration')).toBeInTheDocument()   // only the top level stays
  })
  it('a single twisty toggles one node', () => {
    render(<AstTab stage={stage(factorial, 'ast')} failedStage={null} onReveal={noop} />)
    fireEvent.click(screen.getByRole('tab', { name: 'Outline' }))   // the diagram is the default view
    const twisty = screen.getByRole('button', { name: 'Collapse FunctionDeclaration' })
    fireEvent.click(twisty)
    expect(screen.getByRole('button', { name: 'Expand FunctionDeclaration' })).toHaveAttribute('aria-expanded', 'false')
  })
  it('shows inferred types as chips', () => {
    render(<AstTab stage={stage(factorial, 'ast')} failedStage={null} onReveal={noop} />)
    fireEvent.click(screen.getByRole('tab', { name: 'Outline' }))   // the diagram is the default view
    fireEvent.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.getAllByTitle('Type found by semantic analysis').length).toBeGreaterThan(3)
  })
  it('explains a syntax error instead of showing an empty tree', () => {
    render(<AstTab stage={stage(syntaxError, 'ast')} failedStage="ast" onReveal={noop} />)
    expect(screen.getByText(/found errors/)).toBeInTheDocument()
  })
})

function inspect(result, activeTab, onReveal = noop) {
  return render(<Inspector result={result} activeTab={activeTab} onTab={noop} onReveal={onReveal} />)
}

describe('Inspector tabs', () => {
  it('prompts to run before anything has run', () => {
    inspect(null, 'tac')
    expect(screen.getByText(/to see this stage/)).toBeInTheDocument()
  })

  it('tabs carry the stage status', () => {
    inspect(semanticError, 'semantic')
    expect(screen.getByRole('tab', { name: /Semantic/ })).toHaveAttribute('data-status', 'error')
    expect(screen.getByRole('tab', { name: /Tokens/ })).toHaveAttribute('data-status', 'ok')
    expect(screen.getByRole('tab', { name: /TAC/ })).toHaveAttribute('data-status', 'skipped')
  })

  it('tokens: one row per token, positions, click-to-source', () => {
    const onReveal = vi.fn()
    inspect(factorial, 'tokens', onReveal)
    const rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(stage(factorial, 'tokens').data.length + 1)
    expect(within(rows[1]).getByText('FUNCTION')).toBeInTheDocument()
    expect(within(rows[1]).getByText('1:1')).toBeInTheDocument()
    fireEvent.click(rows[2])
    expect(onReveal).toHaveBeenCalledWith(1, 10)
    expect(screen.getByText('(end of file)')).toBeInTheDocument()
  })

  it('tokens: lexical error still shows the tokens found so far', () => {
    inspect(lexError, 'tokens')
    expect(screen.getAllByRole('row').length).toBeGreaterThan(1)
  })

  it('later tabs say they were skipped when the lexer failed', () => {
    inspect(lexError, 'tac')
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText(/Skipped/)).toBeInTheDocument()
    expect(within(panel).getByText('Tokens')).toBeInTheDocument()
  })

  it('semantic: symbol table with scopes and info log', () => {
    inspect(factorial, 'semantic')
    expect(screen.getByText('factorial(n)')).toBeInTheDocument()
    expect(screen.getByText('result')).toBeInTheDocument()
    expect(screen.getByText(/Function 'factorial' declared/)).toBeInTheDocument()
    expect(screen.getByText('function factorial')).toBeInTheDocument()
  })

  it('semantic: still shows the symbol table for a program with errors', () => {
    inspect(semanticError, 'semantic')
    expect(screen.getByText(/Symbol table/)).toBeInTheDocument()
  })

  it('hasSymbols prunes empty scopes', () => {
    const table = stage(factorial, 'symbol_table').data
    const emptyBlock = table.children[0].children[0]
    expect(hasSymbols(emptyBlock)).toBe(false)
    expect(hasSymbols(table)).toBe(true)
  })

  it('tac: lists every function, labels, and jumps to source', () => {
    const onReveal = vi.fn()
    inspect(factorial, 'tac', onReveal)
    expect(screen.getByText('main:')).toBeInTheDocument()
    expect(screen.getByText('function factorial(n):')).toBeInTheDocument()
    fireEvent.click(screen.getByText('print result'))
    expect(onReveal).toHaveBeenCalledWith(11, 1)
  })

  it('cfg: blocks, edges and unreachable flag', () => {
    inspect(branches, 'cfg')
    fireEvent.click(screen.getByRole('tab', { name: 'Blocks' }))   // the diagram is the default view
    expect(screen.getAllByText(/if (true|false), goes to/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('entry').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/The function ends here/).length).toBeGreaterThan(0)
  })

  it('cfg: dead code from the generator is flagged unreachable', () => {
    const hasUnreachable = JSON.stringify(stage(factorial, 'cfg').data).includes('"reachable": false')
    inspect(factorial, 'cfg')
    expect(screen.queryAllByText('unreachable').length > 0).toBe(hasUnreachable)
  })

  it('optimization: summary counts and change list', () => {
    inspect(optimizing, 'optimization')
    const counts = stage(optimizing, 'optimized_tac').data.instruction_counts
    expect(screen.getByText(String(counts.before))).toBeInTheDocument()
    expect(counts.after).toBeLessThan(counts.before)
    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/constant folding/).length).toBeGreaterThan(0)
  })

  it('optimization: before/after and optimized CFG views', () => {
    inspect(optimizing, 'optimization')
    fireEvent.click(screen.getByRole('tab', { name: 'Before and after' }))
    expect(screen.getByText('Before')).toBeInTheDocument()
    expect(screen.getByText('After')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Optimized CFG' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Blocks' }))   // the diagram is the default view
    expect(screen.getByText('main')).toBeInTheDocument()
  })

  it('optimization: says so when there is nothing to improve', () => {
    const calm = JSON.parse(JSON.stringify(factorial))
    stage(calm, 'optimized_tac').data.changes = []
    stage(calm, 'optimized_tac').data.stats = {}
    inspect(calm, 'optimization')
    expect(screen.getByText(/found nothing to improve/)).toBeInTheDocument()
  })

  it('output: shows output, steps and the verified badge', () => {
    inspect(factorial, 'output')
    expect(screen.getByLabelText('Program output')).toHaveTextContent('120')
    expect(screen.getByText(/Verified:/)).toBeInTheDocument()
    expect(screen.getByText(/Finished in \d+ steps/)).toBeInTheDocument()
    expect(screen.getByText('result')).toBeInTheDocument()
  })

  it('output: keeps partial output when the program fails at run time', () => {
    inspect(runtimeError, 'output')
    expect(screen.getByLabelText('Program output')).toHaveTextContent('1')
    expect(screen.getByText(/stopped with a run-time error/)).toBeInTheDocument()
  })

  it('output: flags a mismatch loudly', () => {
    const broken = JSON.parse(JSON.stringify(factorial))
    stage(broken, 'execution').data.verified = false
    inspect(broken, 'output')
    expect(screen.getByText(/Mismatch/)).toBeInTheDocument()
  })

  it('output: nothing printed is stated, not blank', () => {
    const quiet = JSON.parse(JSON.stringify(factorial))
    stage(quiet, 'execution').data.output = ''
    inspect(quiet, 'output')
    expect(screen.getByText(/printed nothing/)).toBeInTheDocument()
  })

  it('analyze-only result: execution tab asks to press Run', () => {
    inspect(analyzeOnly, 'output')
    expect(screen.getByText(/Press/)).toBeInTheDocument()
  })
})
