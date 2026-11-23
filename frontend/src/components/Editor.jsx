import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import MonacoEditor from '@monaco-editor/react'
import { LANGUAGE, monaco } from '../monacoSetup'

const dark = () => window.matchMedia?.('(prefers-color-scheme: dark)').matches

/** Source editor. Shows compiler diagnostics as squiggles and can scroll to a line. */
const Editor = forwardRef(function Editor({ value, onChange, diagnostics, onRun }, ref) {
  const editorRef = useRef(null)
  const onRunRef = useRef(onRun)
  onRunRef.current = onRun
  const [theme, setTheme] = useState(dark() ? 'nova-dark' : 'nova-light')

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!query) return undefined
    const update = () => setTheme(query.matches ? 'nova-dark' : 'nova-light')
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useImperativeHandle(ref, () => ({
    /** Move the cursor to line:column and flash the line (click-to-source). */
    reveal(line, column = 1) {
      const editor = editorRef.current
      const model = editor?.getModel()
      if (!model || !line) return
      const lineNumber = Math.min(Math.max(line, 1), model.getLineCount())
      editor.revealLineInCenterIfOutsideViewport(lineNumber)
      editor.setPosition({ lineNumber, column: Math.max(column, 1) })
      editor.focus()
      const flash = editor.createDecorationsCollection([
        { range: new monaco.Range(lineNumber, 1, lineNumber, 1),
          options: { isWholeLine: true, className: 'flash-line' } },
      ])
      setTimeout(() => flash.clear(), 1200)
    },
  }), [])

  // Compiler errors and warnings become squiggles under the offending code.
  useEffect(() => {
    const model = editorRef.current?.getModel()
    if (!model) return
    const markers = (diagnostics ?? []).filter((d) => d.line > 0).map((d) => {
      const lineNumber = Math.min(d.line, model.getLineCount())
      const column = Math.max(d.column || 1, 1)
      const word = model.getWordAtPosition({ lineNumber, column })
      return {
        severity: d.severity === 'warning' ? monaco.MarkerSeverity.Warning : monaco.MarkerSeverity.Error,
        message: d.hint ? `${d.message}\n${d.hint}` : d.message,
        startLineNumber: lineNumber,
        startColumn: column,
        endLineNumber: lineNumber,
        endColumn: word && word.endColumn > column ? word.endColumn : column + 1,
        source: d.phase,
      }
    })
    monaco.editor.setModelMarkers(model, 'novalang', markers)
  }, [diagnostics, value])

  return (
    <div className="editor-box">
      <MonacoEditor
        language={LANGUAGE}
        theme={theme}
        value={value}
        onChange={(v) => onChange(v ?? '')}
        onMount={(editor) => {
          editorRef.current = editor
          // Ctrl/Cmd + Enter runs the program.
          editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => onRunRef.current?.())
        }}
        options={{
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          fontSize: 14,
          lineHeight: 22,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          padding: { top: 12, bottom: 12 },
          tabSize: 4,
          renderLineHighlight: 'line',
          automaticLayout: true,
          ariaLabel: 'NovaLang source code',
        }}
      />
    </div>
  )
})

export default Editor
