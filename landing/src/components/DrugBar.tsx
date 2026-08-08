import { useMemo } from 'react'
import {
  INTERVENTIONS,
  USER_PROTOCOL_SPECS,
  HORIZON_WEEKS,
  type AppliedIntervention,
  type InterventionId,
} from '../engine/model'
import { useI18n } from '../i18n'

interface Props {
  protocol: AppliedIntervention[]
  cursorWeek: number
  onAdd: (spec: InterventionId) => void
  onDose: (key: string, dose: number) => void
  onStartWeek: (key: string, week: number) => void
  onRemove: (key: string) => void
}

function snapWeek(week: number): number {
  return Math.round(week * 2) / 2
}

function segmentClosed(iv: AppliedIntervention, cursorWeek: number): boolean {
  const week = snapWeek(cursorWeek)
  return iv.endWeek !== undefined && iv.endWeek <= week + 0.001
}

export function DrugBar({ protocol, cursorWeek, onAdd, onDose, onStartWeek, onRemove }: Props) {
  const { t, fmt } = useI18n()
  const playhead = snapWeek(cursorWeek)
  const activeSpecs = new Set(protocol.map((iv) => iv.spec))
  const available = USER_PROTOCOL_SPECS.filter((spec) => !activeSpecs.has(spec))
  const addHint = fmt(t.ws.addAtWeek, { n: playhead })

  const sorted = useMemo(
    () => [...protocol].sort((a, b) => a.spec.localeCompare(b.spec) || a.startWeek - b.startWeek),
    [protocol],
  )

  return (
    <div className="drugbar drugbar--rail">
      <label className="drugbar__add">
        <span className="mono-label">{t.ws.addDrug}</span>
        <select
          className="drugbar__select"
          value=""
          title={addHint}
          aria-label={`${t.ws.addDrug}. ${addHint}`}
          onChange={(e) => {
            const spec = e.target.value as InterventionId
            if (spec) onAdd(spec)
            e.target.value = ''
          }}
        >
          <option value="">{t.ws.selectDrug}</option>
          {available.map((spec) => (
            <option key={spec} value={spec}>
              {t.engine.interventions[spec]}
            </option>
          ))}
        </select>
        <span className="drugbar__add-hint mono-label">{addHint}</span>
      </label>

      {protocol.length > 0 && (
        <p className="drugbar__playhead-note mono-label">{fmt(t.ws.protocolEditWeek, { n: playhead })}</p>
      )}

      <ul className="drugbar__list">
        {protocol.length === 0 && <li className="drugbar__empty">{t.ws.noDrugs}</li>}
        {sorted.map((iv) => {
          const meta = INTERVENTIONS[iv.spec]
          const name = t.engine.interventions[iv.spec]
          const unit = t.engine.interventionUnits[iv.spec]
          const closed = segmentClosed(iv, cursorWeek)
          const started = iv.startWeek < playhead - 0.001
          const startLocked = closed || started
          return (
            <li
              className="drugbar__item"
              data-inactive={iv.dose <= 0 || undefined}
              data-closed={closed || undefined}
              key={iv.key}
            >
              <div className="drugbar__item-head">
                <span className="drugbar__item-name">{name}</span>
                <button
                  type="button"
                  className="drugbar__remove"
                  onClick={() => onRemove(iv.key)}
                  aria-label={`${t.engine.remove}: ${name}`}
                >
                  ×
                </button>
              </div>
              {closed && iv.endWeek !== undefined && (
                <p className="drugbar__segment-note mono-label">
                  {fmt(t.ws.segmentClosed, { n: iv.endWeek })}
                </p>
              )}
              {!closed && started && (
                <p className="drugbar__segment-note mono-label">
                  {fmt(t.ws.doseEditPlayhead, { n: playhead })}
                </p>
              )}
              <div className="drugbar__item-fields">
                <label className="drugbar__field">
                  <span className="mono-label">{t.ws.startWeekLabel}</span>
                  <input
                    className="drugbar__input tabular"
                    type="number"
                    min={0}
                    max={HORIZON_WEEKS}
                    step={0.5}
                    value={iv.startWeek}
                    disabled={startLocked}
                    aria-label={`${t.ws.startWeekLabel}: ${name}`}
                    onChange={(e) => onStartWeek(iv.key, Number(e.target.value))}
                  />
                </label>
                <label className="drugbar__field">
                  <span className="mono-label">{t.engine.doseLabel}</span>
                  <span className="drugbar__dose-row">
                    <input
                      className="drugbar__input tabular"
                      type="number"
                      min={0}
                      max={meta.max}
                      step={meta.step}
                      value={iv.dose}
                      disabled={closed}
                      aria-label={`${t.engine.doseLabel}: ${name}`}
                      onChange={(e) => onDose(iv.key, Number(e.target.value))}
                    />
                    <span className="drugbar__unit">{unit}</span>
                  </span>
                </label>
              </div>
              {iv.dose <= 0 && (
                <p className="drugbar__warn mono-label">{t.ws.doseZeroWarning}</p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
