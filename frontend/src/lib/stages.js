// The ten pipeline stages (same ids as compiler/pipeline.py) and how they
// map onto the inspector tabs.

export const STAGES = [
  { id: 'source', label: 'Source' },
  { id: 'tokens', label: 'Tokens' },
  { id: 'ast', label: 'Syntax tree' },
  { id: 'semantic', label: 'Semantic' },
  { id: 'symbol_table', label: 'Symbols' },
  { id: 'tac', label: 'TAC' },
  { id: 'cfg', label: 'CFG' },
  { id: 'optimized_tac', label: 'Optimized TAC' },
  { id: 'optimized_cfg', label: 'Optimized CFG' },
  { id: 'execution', label: 'Run' },
]

export const TABS = [
  { id: 'tokens', label: 'Tokens', stages: ['tokens'] },
  { id: 'ast', label: 'Syntax tree', stages: ['ast'] },
  { id: 'semantic', label: 'Semantic Analysis', stages: ['semantic', 'symbol_table'] },
  { id: 'errors', label: 'Errors & Suggestions', stages: ['tokens', 'ast', 'semantic', 'execution'] },
  { id: 'tac', label: 'TAC', stages: ['tac'] },
  { id: 'cfg', label: 'CFG', stages: ['cfg'] },
  { id: 'optimization', label: 'Optimization', stages: ['optimized_tac', 'optimized_cfg'] },
  { id: 'output', label: 'Output', stages: ['execution'] },
]

export const stageLabel = (id) => STAGES.find((s) => s.id === id)?.label ?? id

/** {id: stage} lookup for an API response (empty when nothing has run yet). */
export function stageMap(result) {
  return Object.fromEntries((result?.stages ?? []).map((s) => [s.id, s]))
}

/** ok | warning | error | skipped, or "idle" if the stage was not requested. */
export const statusOf = (map, id) => map[id]?.status ?? 'idle'

const RANK = { error: 4, warning: 3, ok: 2, skipped: 1, idle: 0 }

export function worstStatus(map, ids) {
  return ids.map((id) => statusOf(map, id)).reduce((a, b) => (RANK[b] > RANK[a] ? b : a), 'idle')
}

/** The tab that shows a given stage (the source stage has none). */
export const tabForStage = (id) => TABS.find((t) => t.stages.includes(id))?.id ?? null
