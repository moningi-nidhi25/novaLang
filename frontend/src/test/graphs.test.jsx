import { render, screen, fireEvent } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { factorial, branches, loops, stage } from './fixtures'
import AstTab from '../components/AstTab'
import AstGraph from '../components/AstGraph'
import CfgTab from '../components/CfgTab'
import CfgGraph from '../components/CfgGraph'
import GraphCanvas from '../components/GraphCanvas'
import { TacListing } from '../components/TacTab'

const astRoot = stage(factorial, 'ast').data
const noop = () => {}
// jsdom has no PointerEvent, so events would arrive without clientX / button
beforeAll(() => {
  if (typeof window.PointerEvent === 'undefined') window.PointerEvent = class extends MouseEvent {}
})

const zoomText = () => screen.getByText(/^\d+%$/).textContent

describe('GraphCanvas', () => {
  const draw = () => render(
    <GraphCanvas width={300} height={200} label="Test diagram">{() => <rect width="10" height="10" />}</GraphCanvas>,
  )

  it('starts fitted at 100% and zooms with the buttons', () => {
    draw()
    expect(zoomText()).toBe('100%')
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(zoomText()).toBe('125%')
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(zoomText()).toBe('80%')
  })

  it('Fit to view resets the zoom', () => {
    draw()
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    fireEvent.click(screen.getByRole('button', { name: 'Fit to view' }))
    expect(zoomText()).toBe('100%')
  })

  it('+ and - keys zoom, 0 fits, when the diagram itself has focus', () => {
    draw()
    const box = screen.getByRole('group', { name: 'Test diagram' })
    fireEvent.keyDown(box, { key: '+' })
    expect(zoomText()).toBe('125%')
    fireEvent.keyDown(box, { key: '-' })
    fireEvent.keyDown(box, { key: '-' })
    expect(zoomText()).toBe('80%')
    fireEvent.keyDown(box, { key: '0' })
    expect(zoomText()).toBe('100%')
  })

  it('arrow keys pan the drawing', () => {
    draw()
    const box = screen.getByRole('group', { name: 'Test diagram' })
    const moved = () => box.querySelector('svg > g').getAttribute('transform')
    const before = moved()
    fireEvent.keyDown(box, { key: 'ArrowLeft' })
    expect(moved()).not.toBe(before)
  })

  it('the mouse wheel zooms', () => {
    draw()
    const box = screen.getByRole('group', { name: 'Test diagram' })
    fireEvent.wheel(box, { deltaY: -200, clientX: 10, clientY: 10 })
    expect(Number.parseInt(zoomText(), 10)).toBeGreaterThan(100)
  })

  it('dragging pans and does not count as a click on what it ends on', () => {
    const onClick = vi.fn()
    render(
      <GraphCanvas width={300} height={200} label="Drag test">
        {() => <rect data-testid="r" width="10" height="10" onClick={onClick} />}
      </GraphCanvas>,
    )
    const box = screen.getByRole('group', { name: 'Drag test' })
    const g = () => box.querySelector('svg > g').getAttribute('transform')
    const before = g()
    fireEvent.pointerDown(box, { button: 0, clientX: 100, clientY: 100 })
    fireEvent.pointerMove(window, { clientX: 160, clientY: 130 })
    fireEvent.pointerUp(window)
    expect(g()).not.toBe(before)
    fireEvent.click(screen.getByTestId('r'))   // the click that browsers send after a drag
    expect(onClick).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('r'))   // a later, real click works
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('a plain click (no movement) reaches the node', () => {
    const onClick = vi.fn()
    render(
      <GraphCanvas width={300} height={200} label="Click test">
        {() => <rect data-testid="r" width="10" height="10" onClick={onClick} />}
      </GraphCanvas>,
    )
    const box = screen.getByRole('group', { name: 'Click test' })
    fireEvent.pointerDown(box, { button: 0, clientX: 50, clientY: 50 })
    fireEvent.pointerUp(window)
    fireEvent.click(screen.getByTestId('r'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})

describe('AstGraph', () => {
  const nodes = () => screen.getAllByRole('button', { pressed: false })
    .filter((b) => b.classList.contains('gnode'))

  it('draws one node per AST node', () => {
    const { container } = render(<AstGraph root={astRoot} onReveal={noop} />)
    expect(container.querySelectorAll('.gnode').length).toBeGreaterThan(20)
    expect(screen.getByRole('button', { name: /^FunctionDeclaration factorial.*, line 1$/ })).toBeInTheDocument()
  })

  it('clicking a node selects it, jumps to its source and describes it', () => {
    const onReveal = vi.fn()
    render(<AstGraph root={astRoot} onReveal={onReveal} />)
    const node = screen.getByRole('button', { name: /^FunctionDeclaration factorial/ })
    fireEvent.click(node)
    expect(onReveal).toHaveBeenCalledWith(1, 1)
    expect(node).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/at line 1, column 1/)).toBeInTheDocument()
  })

  it('highlights the path from the selected node up to the root (and nothing else)', () => {
    const { container } = render(<AstGraph root={astRoot} onReveal={noop} />)
    const deep = screen.getAllByRole('button', { name: /^BinaryExpression/ })[0]
    fireEvent.click(deep)
    const onPath = container.querySelectorAll('.gnode[data-onpath]')
    const all = container.querySelectorAll('.gnode')
    expect(onPath.length).toBeGreaterThan(2)
    expect(onPath.length).toBeLessThan(all.length)
    expect(container.querySelectorAll('.gedge[data-onpath]')).toHaveLength(onPath.length - 1)
    expect(container.querySelector('.gnode[data-onpath][data-kind="stmt"]')).not.toBeNull()
  })

  it('the keyboard can select a node', () => {
    const onReveal = vi.fn()
    render(<AstGraph root={astRoot} onReveal={onReveal} />)
    const node = screen.getByRole('button', { name: /^FunctionDeclaration factorial/ })
    fireEvent.keyDown(node, { key: 'Enter' })
    expect(onReveal).toHaveBeenCalled()
  })

  it('collapsing a subtree removes its nodes; expanding brings them back', () => {
    const { container } = render(<AstGraph root={astRoot} onReveal={noop} />)
    const before = container.querySelectorAll('.gnode').length
    fireEvent.click(screen.getByRole('button', { name: 'Collapse FunctionDeclaration subtree' }))
    const after = container.querySelectorAll('.gnode').length
    expect(after).toBeLessThan(before)
    expect(screen.getByText(/1 subtree collapsed/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Expand FunctionDeclaration subtree' }))
    expect(container.querySelectorAll('.gnode').length).toBe(before)
  })

  it('collapsing does not select the node or jump to source', () => {
    const onReveal = vi.fn()
    render(<AstGraph root={astRoot} onReveal={onReveal} />)
    fireEvent.click(screen.getByRole('button', { name: 'Collapse FunctionDeclaration subtree' }))
    expect(onReveal).not.toHaveBeenCalled()
  })

  it('collapsing a node that holds the selection clears the stale highlight', () => {
    const { container } = render(<AstGraph root={astRoot} onReveal={noop} />)
    fireEvent.click(screen.getAllByRole('button', { name: /^BinaryExpression/ })[0])
    fireEvent.click(screen.getByRole('button', { name: 'Collapse FunctionDeclaration subtree' }))
    expect(container.querySelectorAll('.gnode[data-selected]')).toHaveLength(0)
    expect(screen.getByText(/Select a node/)).toBeInTheDocument()
  })

  it('shows the type found by semantic analysis for a selected expression', () => {
    render(<AstGraph root={astRoot} onReveal={noop} />)
    fireEvent.click(screen.getAllByRole('button', { name: /^BinaryExpression/ })[0])
    expect(screen.getByTitle('Type found by semantic analysis')).toBeInTheDocument()
  })
})

describe('AstTab views', () => {
  it('opens on the diagram and can switch to the outline and back', () => {
    render(<AstTab stage={stage(factorial, 'ast')} failedStage={null} onReveal={noop} />)
    expect(screen.getByRole('tab', { name: 'Diagram' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('group', { name: 'Syntax tree diagram' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Outline' }))
    expect(screen.queryByRole('group', { name: 'Syntax tree diagram' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Expand all' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Diagram' }))
    expect(screen.getByRole('group', { name: 'Syntax tree diagram' })).toBeInTheDocument()
  })
})

describe('CfgGraph', () => {
  const cfgOf = (r) => stage(r, 'cfg').data

  it('draws every block, with its instructions, for the selected function', () => {
    const cfg = cfgOf(branches)
    const { container } = render(<CfgGraph cfg={cfg} onReveal={noop} />)
    expect(container.querySelectorAll('.gblock')).toHaveLength(cfg.functions[0].blocks.length)
    const text = container.textContent
    for (const ins of cfg.functions[0].blocks[0].instructions) expect(text).toContain(ins.text.slice(0, 20))
  })

  it('draws one arrow per edge, and labels the two outcomes of a condition', () => {
    const cfg = cfgOf(branches)
    const { container } = render(<CfgGraph cfg={cfg} onReveal={noop} />)
    expect(container.querySelectorAll('.cfg-edge')).toHaveLength(cfg.functions[0].edges.length)
    expect(container.querySelectorAll('.gedge-label').length).toBeGreaterThan(0)
    const labels = [...container.querySelectorAll('.gedge-label')].map((n) => n.textContent)
    expect(labels).toContain('true')
    expect(labels).toContain('false')
  })

  it('marks loop edges (the program with loops) as going back', () => {
    const { container } = render(<CfgGraph cfg={cfgOf(loops)} onReveal={noop} />)
    expect(container.querySelectorAll('g[data-back]').length).toBeGreaterThanOrEqual(2)
  })

  it('selecting a block explains where it goes and dims unrelated blocks', () => {
    const { container } = render(<CfgGraph cfg={cfgOf(branches)} onReveal={noop} />)
    fireEvent.click(screen.getByRole('button', { name: /^Block B1(,|$)/ }))
    expect(screen.getAllByText(/goes to|falls through to/).length).toBeGreaterThan(0)
    expect(container.querySelectorAll('.gblock[data-selected]')).toHaveLength(1)
    expect(container.querySelectorAll('.gblock[data-dim]').length).toBeGreaterThan(0)
    expect(container.querySelectorAll('g[data-hot]').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: /^Block B1(,|$)/ }))   // click again to clear
    expect(container.querySelectorAll('.gblock[data-selected]')).toHaveLength(0)
    expect(container.querySelectorAll('[data-dim]')).toHaveLength(0)
  })

  it('clicking an instruction jumps to its source line', () => {
    const onReveal = vi.fn()
    render(<CfgGraph cfg={cfgOf(factorial)} onReveal={onReveal} />)
    const rows = screen.getAllByRole('button', { name: /source line \d+/ })
    fireEvent.click(rows[0])
    expect(onReveal).toHaveBeenCalledTimes(1)
    expect(onReveal.mock.calls[0][0]).toBeGreaterThan(0)
  })

  it('shows a function picker only when there are several functions', () => {
    const { rerender } = render(<CfgGraph cfg={cfgOf(factorial)} onReveal={noop} />)
    expect(screen.getByRole('tablist', { name: 'Function' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'main' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: 'factorial' }))
    expect(screen.getByRole('group', { name: 'Control-flow graph of factorial' })).toBeInTheDocument()
    const single = { functions: [cfgOf(branches).functions[0]] }
    rerender(<CfgGraph cfg={single} onReveal={noop} />)
    expect(screen.queryByRole('tablist', { name: 'Function' })).toBeNull()
  })

  it('marks unreachable blocks', () => {
    const cfg = JSON.parse(JSON.stringify(cfgOf(branches)))
    cfg.functions[0].blocks[1].reachable = false
    const { container } = render(<CfgGraph cfg={cfg} onReveal={noop} />)
    expect(container.querySelectorAll('.gblock[data-unreachable]')).toHaveLength(1)
    expect(screen.getAllByText('unreachable').length).toBeGreaterThan(0)
  })

  it('says so when a function has no instructions', () => {
    render(<CfgGraph cfg={{ functions: [{ function: 'main', entry: null, blocks: [], edges: [] }] }} onReveal={noop} />)
    expect(screen.getByText('(no instructions)')).toBeInTheDocument()
  })
})

describe('CfgTab views', () => {
  it('opens on the diagram and switches to block cards and back', () => {
    render(<CfgTab stage={stage(branches, 'cfg')} failedStage={null} onReveal={noop} />)
    expect(screen.getByRole('group', { name: /Control-flow graph of main/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Blocks' }))
    expect(screen.queryByRole('group', { name: /Control-flow graph of main/ })).toBeNull()
    expect(screen.getAllByText(/if (true|false), goes to/).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('tab', { name: 'Diagram' }))
    expect(screen.getByRole('group', { name: /Control-flow graph of main/ })).toBeInTheDocument()
  })
})

describe('TAC jump highlighting', () => {
  const fn = stage(loops, 'tac').data.functions.find((f) => f.kind === 'main')
  const rows = () => screen.getAllByRole('button')

  it('selecting a jump lights up the label it goes to', () => {
    const { container } = render(<TacListing fn={fn} onReveal={noop} />)
    const jump = fn.instructions.find((i) => i.op === 'goto')
    fireEvent.click(rows().find((r) => r.textContent.includes(jump.text)))
    const related = container.querySelectorAll('[data-related]')
    expect(related.length).toBeGreaterThan(0)
    expect(related[0].textContent).toContain(`${jump.result}:`)
  })

  it('selecting a label lights up every jump that targets it', () => {
    const { container } = render(<TacListing fn={fn} onReveal={noop} />)
    const jump = fn.instructions.find((i) => i.op === 'goto')
    const label = fn.instructions.find((i) => i.op === 'label' && i.result === jump.result)
    const sources = fn.instructions.filter((i) => ['goto', 'if_false', 'if_true'].includes(i.op) && i.result === label.result)
    fireEvent.click(rows().find((r) => r.textContent.endsWith(`${label.result}:`)))
    expect(container.querySelectorAll('[data-related]')).toHaveLength(sources.length)
  })

  it('clicking again clears the highlight, and ordinary lines highlight nothing', () => {
    const { container } = render(<TacListing fn={fn} onReveal={noop} />)
    const jump = fn.instructions.find((i) => i.op === 'goto')
    const row = rows().find((r) => r.textContent.includes(jump.text))
    fireEvent.click(row)
    fireEvent.click(row)
    expect(container.querySelectorAll('[data-related]')).toHaveLength(0)
    const plain = fn.instructions.find((i) => i.op === 'copy')
    fireEvent.click(rows().find((r) => r.textContent.includes(plain.text)))
    expect(container.querySelectorAll('[data-related]')).toHaveLength(0)
  })

  it('still jumps to source when a line with a source position is clicked', () => {
    const onReveal = vi.fn()
    render(<TacListing fn={fn} onReveal={onReveal} />)
    const ins = fn.instructions.find((i) => i.line)
    fireEvent.click(rows().find((r) => r.textContent.includes(ins.text)))
    expect(onReveal).toHaveBeenCalledWith(ins.line, ins.column)
  })
})
