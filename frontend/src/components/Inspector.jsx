import { TABS, stageMap, worstStatus } from '../lib/stages'
import TokensTab from './TokensTab'
import AstTab from './AstTab'
import SemanticTab from './SemanticTab'
import TacTab from './TacTab'
import CfgTab from './CfgTab'
import OptimizationTab from './OptimizationTab'
import OutputTab from './OutputTab'
import ErrorsTab from './ErrorsTab'

/** Tabbed view of every stage's output. */
export default function Inspector({ result, source = '', activeTab, onTab, onReveal }) {
  const map = stageMap(result)
  const failedStage = result?.failed_stage ?? null
  const common = { failedStage, onReveal }

  return (
    <section className="inspector" aria-label="Compiler stages">
      <div className="tabs" role="tablist" aria-label="Stage output">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={activeTab === t.id}
            aria-controls="tabpanel"
            className="tab"
            data-status={worstStatus(map, t.stages)}
            onClick={() => onTab(t.id)}
          >
            <span className="tab-dot" aria-hidden="true" />
            {t.label}
          </button>
        ))}
      </div>
      <div className="tabpanel" id="tabpanel" role="tabpanel" aria-labelledby={`tab-${activeTab}`} tabIndex={0}>
        {activeTab === 'tokens' && <TokensTab stage={map.tokens} {...common} />}
        {activeTab === 'ast' && <AstTab stage={map.ast} {...common} />}
        {activeTab === 'semantic' && (
          <SemanticTab semantic={map.semantic} symbols={map.symbol_table} source={source} {...common} />
        )}
        {activeTab === 'errors' && <ErrorsTab result={result} onReveal={onReveal} />}
        {activeTab === 'tac' && <TacTab stage={map.tac} {...common} />}
        {activeTab === 'cfg' && <CfgTab stage={map.cfg} {...common} />}
        {activeTab === 'optimization' && (
          <OptimizationTab tac={map.optimized_tac} cfg={map.optimized_cfg} {...common} />
        )}
        {activeTab === 'output' && <OutputTab stage={map.execution} failedStage={failedStage} />}
      </div>
    </section>
  )
}
