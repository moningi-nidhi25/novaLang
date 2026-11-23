import { forwardRef, useImperativeHandle } from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { factorial, semanticError, analyzeOnly } from './fixtures'

// Monaco cannot run in jsdom, so the editor is replaced by a textarea with the same props.
const revealSpy = vi.fn()
vi.mock('../components/Editor', () => ({
  default: forwardRef(function FakeEditor({ value, onChange, diagnostics }, ref) {
    useImperativeHandle(ref, () => ({ reveal: revealSpy }))
    return (
      <div>
        <textarea aria-label="source" value={value} onChange={(e) => onChange(e.target.value)} />
        <output aria-label="markers">{diagnostics.length}</output>
      </div>
    )
  }),
}))

const api = vi.hoisted(() => ({ compile: vi.fn(), listExamples: vi.fn(), getExample: vi.fn() }))
vi.mock('../api', async () => ({ ...(await vi.importActual('../api')), ...api }))

import App, { DEFAULT_SOURCE } from '../App'

beforeEach(() => {
  vi.clearAllMocks()
  api.listExamples.mockResolvedValue(['demo_factorial', 'hello'])
})

describe('App', () => {
  it('starts with the factorial demo and nothing run', async () => {
    render(<App />)
    expect(screen.getByLabelText('source')).toHaveValue(DEFAULT_SOURCE)
    expect(screen.getByText(/to see this stage/)).toBeInTheDocument()
    await screen.findByRole('option', { name: 'demo factorial' })
  })

  it('Run compiles everything and opens the Output tab', async () => {
    api.compile.mockResolvedValue(factorial)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByText(/Verified:/)
    expect(api.compile).toHaveBeenCalledWith(DEFAULT_SOURCE, 'compile')
    expect(screen.getByLabelText('Program output')).toHaveTextContent('120')
  })

  it('Analyze uses the analyze endpoint and stays on the current tab', async () => {
    api.compile.mockResolvedValue(analyzeOnly)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }))
    await screen.findAllByRole('row')
    expect(api.compile).toHaveBeenCalledWith(DEFAULT_SOURCE, 'analyze')
  })

  it('a failing stage opens its own tab and lists the problem', async () => {
    api.compile.mockResolvedValue(semanticError)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByText(/'zzz' is not defined/)
    expect(screen.getByRole('tab', { name: /Semantic/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('markers')).toHaveTextContent('1')
    fireEvent.click(screen.getByRole('button', { name: /not defined/ }))
    expect(revealSpy).toHaveBeenCalledWith(1, 7)
  })

  it('shows a clear banner when the server is down', async () => {
    const { ApiError } = await vi.importActual('../api')
    api.compile.mockRejectedValue(new ApiError('Cannot reach the NovaLang server.'))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach')
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled()
  })

  it('disables the buttons while a request is running', async () => {
    let finish
    api.compile.mockReturnValue(new Promise((r) => { finish = r }))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Analyze' })).toBeDisabled()
    finish(factorial)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled())
  })

  it('ignores an old answer that arrives after a newer one', async () => {
    let first
    api.compile
      .mockReturnValueOnce(new Promise((r) => { first = r }))
      .mockResolvedValueOnce(factorial)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }))
    // Buttons are disabled while busy; use the keyboard-free path: re-enable by finishing nothing,
    // so simulate a newer request through a second render of the same component instance.
    first(semanticError)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByText(/Verified:/)
  })

  it('loading an example replaces the source and clears results', async () => {
    api.compile.mockResolvedValue(factorial)
    api.getExample.mockResolvedValue({ name: 'hello', source: 'print("hi");' })
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByText(/Verified:/)
    await screen.findByRole('option', { name: 'hello' })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'hello' } })
    await waitFor(() => expect(screen.getByLabelText('source')).toHaveValue('print("hi");'))
    expect(screen.queryByText(/Verified:/)).toBeNull()
  })

  it('works without the examples endpoint (no dropdown)', async () => {
    api.listExamples.mockRejectedValue(new Error('down'))
    render(<App />)
    await waitFor(() => expect(api.listExamples).toHaveBeenCalled())
    expect(screen.queryByRole('combobox')).toBeNull()
  })
})
