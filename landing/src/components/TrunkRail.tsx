import { useState } from 'react'
import { INDICATOR_BY_ID, type AppliedIntervention, type IndicatorId, type InterventionId } from '../engine/model'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'
import { DrugBar } from './DrugBar'

type TrunkTab = 'baseline' | 'protocol'

interface TrunkMarker {
  id: IndicatorId
  value: string
  unit: string
}

interface Props {
  trunkMarkers: TrunkMarker[]
  protocol: AppliedIntervention[]
  cursorWeek: number
  onAdd: (spec: InterventionId) => void
  onDose: (key: string, dose: number) => void
  onStartWeek: (key: string, week: number) => void
  onRemove: (key: string) => void
}

export function TrunkRail({
  trunkMarkers,
  protocol,
  cursorWeek,
  onAdd,
  onDose,
  onStartWeek,
  onRemove,
}: Props) {
  const { t } = useI18n()
  const f = t.hero.figure
  const [tab, setTab] = useState<TrunkTab>('baseline')

  return (
    <aside className="ensemble-tree__trunk-rail" aria-label={f.baseline}>
      <div className="trunk-rail__tabs" role="tablist" aria-label={f.panel}>
        <button
          type="button"
          className="trunk-rail__tab"
          role="tab"
          id="trunk-tab-baseline"
          aria-selected={tab === 'baseline'}
          aria-controls="trunk-panel-baseline"
          data-on={tab === 'baseline'}
          onClick={() => setTab('baseline')}
        >
          {t.ws.trunkTabBaseline}
        </button>
        <button
          type="button"
          className="trunk-rail__tab"
          role="tab"
          id="trunk-tab-protocol"
          aria-selected={tab === 'protocol'}
          aria-controls="trunk-panel-protocol"
          data-on={tab === 'protocol'}
          onClick={() => setTab('protocol')}
        >
          {t.ws.trunkTabProtocol}
          {protocol.length > 0 && (
            <span className="trunk-rail__tab-count tabular" aria-hidden="true">
              {protocol.length}
            </span>
          )}
        </button>
      </div>

      {tab === 'baseline' && (
        <div
          className="trunk-rail__panel"
          role="tabpanel"
          id="trunk-panel-baseline"
          aria-labelledby="trunk-tab-baseline"
        >
          <p className="ensemble-tree__trunk-title mono-label">{f.baseline.toUpperCase()}</p>
          <ul className="ensemble-tree__trunk-list">
            {trunkMarkers.map((m) => (
              <li key={m.id} className="ensemble-tree__trunk-item">
                <span className="ensemble-tree__trunk-name">
                  {indicatorName(t, INDICATOR_BY_ID[m.id])}
                </span>
                <span className="ensemble-tree__trunk-val tabular">
                  {m.value}
                  <span className="ensemble-tree__trunk-unit">{m.unit}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {tab === 'protocol' && (
        <div
          className="trunk-rail__panel trunk-rail__panel--protocol"
          role="tabpanel"
          id="trunk-panel-protocol"
          aria-labelledby="trunk-tab-protocol"
        >
          <DrugBar
            protocol={protocol}
            cursorWeek={cursorWeek}
            onAdd={onAdd}
            onDose={onDose}
            onStartWeek={onStartWeek}
            onRemove={onRemove}
          />
        </div>
      )}
    </aside>
  )
}
