// Real API responses, generated from the Python backend (see tests/ in the repo root).
import factorial from './factorial.json'
import optimizing from './optimizing.json'
import syntaxError from './syntax_error.json'
import semanticError from './semantic_error.json'
import runtimeError from './runtime_error.json'
import lexError from './lex_error.json'
import analyzeOnly from './analyze_only.json'
import branches from './branches.json'
import loops from './loops.json'

export { factorial, optimizing, syntaxError, semanticError, runtimeError, lexError, analyzeOnly, branches, loops }
export const stage = (result, id) => result.stages.find((s) => s.id === id)
