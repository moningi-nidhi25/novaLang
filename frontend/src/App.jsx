import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, compile, getExample, listExamples } from './api'
import Editor from './components/Editor'
import StageRail from './components/StageRail'
import Inspector from './components/Inspector'
import Diagnostics, { collectDiagnostics } from './components/Diagnostics'
import { tabForStage } from './lib/stages'

export const DEFAULT_SOURCE = `function factorial(n) {
    if (n <= 1) {
        return 1;
    }

    return n * factorial(n - 1);
}

let result = factorial(5);

print(result);
`

export default function App() {
  const [source, setSource] = useState(DEFAULT_SOURCE)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [apiError, setApiError] = useState(null)
  const [tab, setTab] = useState('tokens')
  const [examples, setExamples] = useState([])
  const editor = useRef(null)
  const latest = useRef(0) // ignore answers that arrive after a newer request

  useEffect(() => {
    listExamples().then(setExamples).catch(() => {}) // the dropdown is optional
  }, [])

  const execute = useCallback(async (endpoint) => {
    const id = ++latest.current
    setBusy(true)
    setApiError(null)
    try {
      const data = await compile(source, endpoint)
      if (id !== latest.current) return
      setResult(data)
      // Jump to where the learner should look: the failing stage, else the program output.
      const failedTab = data.failed_stage && tabForStage(data.failed_stage)
      if (failedTab) setTab(failedTab)
      else if (endpoint === 'compile') setTab('output')
    } catch (e) {
      if (id === latest.current) setApiError(e instanceof ApiError ? e.message : 'Something went wrong.')
    } finally {
      if (id === latest.current) setBusy(false)
    }
  }, [source])

  const run = useCallback(() => execute('compile'), [execute])
  const analyze = useCallback(() => execute('analyze'), [execute])
  const reveal = useCallback((line, column) => editor.current?.reveal(line, column), [])

  const loadExample = async (name) => {
    if (!name) return
    try {
      const ex = await getExample(name)
      setSource(ex.source)
      setResult(null)
      setApiError(null)
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : 'Could not load the example.')
    }
  }

  const diagnostics = collectDiagnostics(result)

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">NovaLang <span>playground</span></h1>
        <div className="actions">
          {examples.length > 0 && (
            <label className="select-wrap">
              <span className="sr-only">Load an example program</span>
              <select value="" onChange={(e) => loadExample(e.target.value)}>
                <option value="">Load example…</option>
                {examples.map((n) => <option key={n} value={n}>{n.replace(/_/g, ' ')}</option>)}
              </select>
            </label>
          )}
          <button type="button" className="btn" onClick={analyze} disabled={busy}>Analyze</button>
          <button type="button" className="btn primary" onClick={run} disabled={busy}
                  title="Ctrl+Enter / Cmd+Enter">
            Run
          </button>
        </div>
      </header>

      <StageRail result={result} activeTab={tab} onSelect={setTab} />

      {apiError && <p className="banner" role="alert">{apiError}</p>}

      <main className="workspace" aria-busy={busy}>
        <div className="left">
          <Editor ref={editor} value={source} onChange={setSource} diagnostics={diagnostics} onRun={run} />
          <Diagnostics items={diagnostics} onReveal={reveal} />
        </div>
        <Inspector result={result} source={source} activeTab={tab} onTab={setTab} onReveal={reveal} />
      </main>
    </div>
  )
}
