import { useMemo } from 'react'
import {
  INDICATOR_BY_ID,
  formatValue,
  HORIZON_WEEKS,
  type IndicatorId,
} from '../engine/model'
import { WEEKS, stopReasons, type RunResult } from '../engine/cohort'
import { SNAPSHOT_PANEL, flagOf, type Baselines, type Subject } from '../engine/subject'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'
import { stopVitalId, summarizeBranch, isSenescenceBranchStop } from '../lib/branchSummary'
import { ageAtWeek } from '../engine/mortality'
import type { FanAxisMode } from '../lib/simulationTree'

interface Props {
  result: RunResult
  subject: Subject
  baselines: Baselines
  displayId: IndicatorId
  fanAxisMode: FanAxisMode
  cursorWeek: number
  selectedBranch: number | null
  onPickIndicator: (id: IndicatorId) => void
}

const FACTOR_LABEL: Record<string, keyof import('../i18n/locales/en').Dict['engine']['factors']> = {
  sleep: 'sleep',
  movement: 'movement',
  diet: 'diet',
  stress: 'stress',
}

const OUTCOME_BAND = 0.1

function DeltaMoves({
  rows,
  tone,
  label,
  t,
}: {
  rows: { id: IndicatorId; baseline: number; end: number }[]
  tone: 'up' | 'down'
  label: string
  t: ReturnType<typeof useI18n>['t']
}) {
  if (rows.length === 0) return null
  return (
    <div className={`biopanel__summary-moves biopanel__summary-moves--${tone}`}>
      <span className="biopanel__summary-moves-kicker mono-label">{label}</span>
      <ul className="biopanel__summary-deltas">
        {rows.map((row) => (
          <li key={row.id}>
            <span className="biopanel__delta-name">{indicatorName(t, INDICATOR_BY_ID[row.id])}</span>
            <span className="biopanel__delta-vals tabular">
              {formatValue(row.id, row.baseline)}
              <span className="biopanel__arrow" aria-hidden="true">
                →
              </span>
              {formatValue(row.id, row.end)}
              <span className="biopanel__delta-unit">{INDICATOR_BY_ID[row.id].unit}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function BiomarkerPanel({
  result,
  subject,
  baselines,
  displayId,
  fanAxisMode,
  cursorWeek,
  selectedBranch,
  onPickIndicator,
}: Props) {
  const { t, fmt } = useI18n()
  const week = Math.min(WEEKS - 1, Math.round(cursorWeek))
  const stat = result.stats[week]

  const branch = selectedBranch
  const summary = useMemo(
    () => (branch !== null ? summarizeBranch(result, branch, cursorWeek, baselines) : null),
    [branch, result, cursorWeek, baselines],
  )

  const branchValues = useMemo(() => {
    if (!summary) return null
    return new Map(summary.panel.map((row) => [row.id, row.end]))
  }, [summary])

  const stops = stopReasons(result).slice(0, 3)

  const burdenDir =
    summary && summary.scoreGain > OUTCOME_BAND
      ? t.ws.branchSummaryBurdenUp
      : summary && summary.scoreGain < -OUTCOME_BAND
        ? t.ws.branchSummaryBurdenDown
        : t.ws.branchSummaryBurdenFlat

  const burdenPct =
    summary && result.baselineScore > 0
      ? Math.abs((summary.scoreGain / result.baselineScore) * 100).toFixed(0)
      : '0'

  const stopVital =
    summary && summary.stopWeek >= 0 && summary.stopWeek <= week && branch !== null
      ? stopVitalId(result, branch)
      : null

  const stopSenescence =
    summary && summary.stopWeek >= 0 && summary.stopWeek <= week && branch !== null
      ? isSenescenceBranchStop(result, branch)
      : false

  return (
    <aside className="biopanel">
      <header className="biopanel__head pane__head">
        <h3 className="pane__title">{t.ws.biomarkersTitle}</h3>
        <span className="mono-label">
          {branch !== null
            ? t.ws.biomarkersBranchNote
            : fanAxisMode === 'composite'
              ? t.ws.biomarkersCompositeNote
              : t.ws.biomarkersIndicatorNote}
        </span>
      </header>

      {summary && (
        <section className="biopanel__summary" data-outcome={summary.outcome}>
          <div className="biopanel__summary-head">
            <h4 className="biopanel__summary-title">{t.ws.branchSummaryTitle}</h4>
            <span className="biopanel__outcome">{t.ws.branchOutcomeLabel[summary.outcome]}</span>
          </div>

          {stopSenescence && summary.stopWeek >= 0 && summary.stopWeek <= week && (
            <p className="biopanel__summary-stop-lead">
              {fmt(t.ws.branchSummaryStoppedAgeLead, {
                n: summary.stopWeek,
                age: ageAtWeek(subject, summary.stopWeek).toFixed(1),
              })}
            </p>
          )}
          {stopVital && !stopSenescence && (
            <p className="biopanel__summary-stop-lead">
              {fmt(t.ws.branchSummaryStoppedLead, {
                n: summary.stopWeek,
                vital: indicatorName(t, INDICATOR_BY_ID[stopVital]),
              })}
            </p>
          )}

          {summary.outcome !== 'stopped' && (
            <p className="biopanel__summary-lead">
              {fmt(t.ws.branchSummaryComposite, {
                n: summary.week,
                burdenDir,
                burdenPct,
                rank: summary.percentile,
              })}
            </p>
          )}
          {summary.outcome === 'stopped' && (
            <p className="biopanel__summary-lead biopanel__summary-lead--muted">
              {fmt(t.ws.branchSummaryComposite, {
                n: summary.week,
                burdenDir,
                burdenPct,
                rank: summary.percentile,
              })}
            </p>
          )}
          {summary.outcome === 'improved' && (
            <DeltaMoves rows={summary.improved} tone="up" label={t.ws.branchSummaryGainsLabel} t={t} />
          )}
          {(summary.outcome === 'worsened' || summary.outcome === 'stopped') && (
            <DeltaMoves rows={summary.worsened} tone="down" label={t.ws.branchSummaryLossesLabel} t={t} />
          )}
          {summary.stopWeek < 0 && summary.week >= HORIZON_WEEKS && (
            <p className="biopanel__summary-horizon">
              {fmt(t.ws.branchSummaryHorizon, { n: HORIZON_WEEKS })}
            </p>
          )}
          <div className="biopanel__summary-lifestyle">
            <span className="mono-label">{t.ws.branchSummaryLifestyle}</span>
            <ul className="biopanel__summary-factors">
              {summary.factors.map((factor) => {
                const key = FACTOR_LABEL[factor.id]
                return (
                  <li key={factor.id} data-tier={factor.tier}>
                    <span>{key ? t.engine.factors[key] : factor.id}</span>
                    <b>{t.ws.factorTier[factor.tier]}</b>
                  </li>
                )
              })}
            </ul>
          </div>
        </section>
      )}

      <ul className="biopanel__list">
        {SNAPSHOT_PANEL.map((id) => {
          const base = baselines[id]
          const flag = flagOf(subject, id, base)
          const onFan = fanAxisMode === 'indicator' && id === displayId
          const branchVal = branchValues?.get(id)
          const showBranch = branchVal !== undefined
          return (
            <li
              key={id}
              className="biopanel__row"
              data-flag={flag}
              data-on={onFan}
              data-branch={showBranch}
            >
              <button
                type="button"
                className="biopanel__pick"
                onClick={() => onPickIndicator(id)}
                aria-pressed={onFan}
                title={onFan ? t.ws.indicatorFocusOff : t.ws.indicatorFocusOn}
              >
                <span className="biopanel__name">{indicatorName(t, INDICATOR_BY_ID[id])}</span>
                <span className="biopanel__vals tabular">
                  <span>{formatValue(id, base)}</span>
                  {showBranch && (
                    <>
                      <span className="biopanel__arrow" aria-hidden="true">
                        →
                      </span>
                      <span>{formatValue(id, branchVal)}</span>
                    </>
                  )}
                  {!showBranch && onFan && (
                    <>
                      <span className="biopanel__arrow" aria-hidden="true">
                        →
                      </span>
                      <span>{formatValue(id, stat.p50)}</span>
                    </>
                  )}
                </span>
                <span className="biopanel__unit">{INDICATOR_BY_ID[id].unit}</span>
                {onFan && !showBranch && (
                  <span className="biopanel__band tabular">
                    p05 {formatValue(id, stat.p05)} · p95 {formatValue(id, stat.p95)}
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>

      {stops.length > 0 && branch === null && (
        <section className="biopanel__stops">
          <p className="mono-label">{t.ws.stopReasons}</p>
          <ul>
            {stops.map((row) => (
              <li key={row.id}>
                <span>
                  {row.id === 'senescence'
                    ? t.ws.stopSenescence
                    : indicatorName(t, INDICATOR_BY_ID[row.id])}
                </span>
                <b className="tabular">{row.count}</b>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  )
}
