// Monaco is bundled with the app (no CDN), so the playground works offline.
// This module is imported once, for its side effects.

import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import { loader } from '@monaco-editor/react'

self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
loader.config({ monaco })

export const LANGUAGE = 'novalang'

monaco.languages.register({ id: LANGUAGE })
monaco.languages.setLanguageConfiguration(LANGUAGE, {
  comments: { lineComment: '//', blockComment: ['/*', '*/'] },
  brackets: [['{', '}'], ['[', ']'], ['(', ')']],
  autoClosingPairs: [
    { open: '{', close: '}' },
    { open: '[', close: ']' },
    { open: '(', close: ')' },
    { open: '"', close: '"', notIn: ['string'] },
  ],
})

// Keywords come from compiler/lexer/tokens.py.
monaco.languages.setMonarchTokensProvider(LANGUAGE, {
  keywords: ['let', 'function', 'return', 'if', 'else', 'while', 'for', 'break', 'continue', 'print'],
  constants: ['true', 'false', 'nil'],
  builtins: ['len'],
  tokenizer: {
    root: [
      [/[A-Za-z_]\w*/, { cases: {
        '@keywords': 'keyword', '@constants': 'constant', '@builtins': 'support', '@default': 'identifier' } }],
      [/\d+\.\d+([eE][+-]?\d+)?/, 'number.float'],
      [/\d+/, 'number'],
      [/"/, 'string', '@string'],
      [/\/\/.*$/, 'comment'],
      [/\/\*/, 'comment', '@comment'],
      [/[+\-*/%=!<>&|]+/, 'operator'],
    ],
    string: [[/[^\\"]+/, 'string'], [/\\./, 'string.escape'], [/"/, 'string', '@pop']],
    comment: [[/[^/*]+/, 'comment'], [/\*\//, 'comment', '@pop'], [/[/*]/, 'comment']],
  },
})

const common = { base: undefined, inherit: true }
monaco.editor.defineTheme('nova-light', {
  ...common, base: 'vs',
  rules: [
    { token: 'keyword', foreground: '0F6E8C', fontStyle: 'bold' },
    { token: 'constant', foreground: '8A4F00' },
    { token: 'support', foreground: '5B3FA0' },
    { token: 'number', foreground: '1F6B3D' },
    { token: 'number.float', foreground: '1F6B3D' },
    { token: 'string', foreground: 'A3392E' },
    { token: 'comment', foreground: '7A8591', fontStyle: 'italic' },
  ],
  colors: { 'editor.background': '#FFFFFF', 'editor.lineHighlightBackground': '#F2F5F7' },
})
monaco.editor.defineTheme('nova-dark', {
  ...common, base: 'vs-dark',
  rules: [
    { token: 'keyword', foreground: '6CC4E2', fontStyle: 'bold' },
    { token: 'constant', foreground: 'E0A83A' },
    { token: 'support', foreground: 'B9A3F0' },
    { token: 'number', foreground: '7FD1A0' },
    { token: 'number.float', foreground: '7FD1A0' },
    { token: 'string', foreground: 'F0948B' },
    { token: 'comment', foreground: '7F8C99', fontStyle: 'italic' },
  ],
  colors: { 'editor.background': '#1A222B', 'editor.lineHighlightBackground': '#212B36' },
})

export { monaco }
