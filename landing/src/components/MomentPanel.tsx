import { useMemo } from 'react'
import {
  INDICATOR_BY_ID,
  formatValue,
  isControl,
  simulate,
  type IndicatorId,
  type Scenario,
} from '../engine/model'
import {
  attribution,
  branchRisks,
  divergence,
  protocolDiff,
  protocolEvents,
  type ProtocolEvent,
} from '../engine/graph'
import type { Baselines, Subject } from '../engine/subject'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'

interface Props {
  scenario: Scenario
  parent: Scenario | null
  control: Scenario
  rival: Scenario | null
  subject: Subject
  baselines: Baselines
  week: number
  panel: IndicatorId[]
  label: (s: Scenario) => string
  eventText: (e: ProtocolEvent) => string
  onCompare: () => void
}

/**
 * What is happening at the point on the timeline you are looking at.
 *
 * Moving a playhead used to change the numbers without explaining them. This
 * panel is the explanation: which change this branch is living through, how
 * long ago it happened, how far the panel has moved from the control, which
 * intervention the model holds responsible, what is starting to go wrong, and
 * what this branch does that its neighbour does not.
 */
export function MomentPanel({
  scenario,
  parent,
  control,
  rival,
  subject,
  baselines,
  week,
  panel,
  label,
  eventText,
  onCompare,
}: Props) {
  const { t, fmt } = useI18n()
  const control_ = isControl(scenario)

  // the most recent protocol change at or before the playhead: that is the one
  // the current state is a consequence of
  const lastEvent = useMemo(() => {
    const events = protocolEvents(scenario).filter((e) => e.week <= week)
    return events[events.length - 1] ?? null
  }, [scenario, week])

  const deviations = useMemo(() => {
    const at = Math.round(week * 2)
    return panel
      .map((id) => {
        const value = simulate(scenario, id, baselines).points[at].value
        const base = simulate(control, id, baselines).points[at].value
        return { id, delta: value - base }
      })
      .filter((d) => Math.abs(d.delta) > 1e-9)
      .sort(
        (a, b) =>
          Math.abs(b.delta / INDICATOR_BY_ID[b.id].sigma) -
          Math.abs(a.delta / INDICATOR_BY_ID[a.id].sigma),
      )
      .slice(0, 5)
  }, [scenario, control, baselines, panel, week])

  // attribution is read on whichever indicator this branch has moved most: a
  // contribution split computed on an analyte nothing touched is all noise
  const lead = deviations[0]?.id ?? panel[0]
  const contrib = useMemo(
    () => (control_ ? null : attribution(scenario, control, lead, week, baselines)),
    [control_, scenario, control, lead, week, baselines],
  )

  const risks = useMemo(
    () => branchRisks(scenario, subject, baselines, week),
    [scenario, subject, baselines, week],
  )

  const why = useMemo(() => {
    if (rival) return protocolDiff(scenario, rival, week)
    return divergence(scenario, parent)
  }, [scenario, rival, parent, week])

  return (
    <aside className="moment" data-hint={t.ws.hints.moment}>
      <header className="moment__head">
        <span className="mono-label">
          {t.ws.week} {Math.round(week * 2) / 2}
        </span>
        <span className="moment__branch">{label(scenario)}</span>
      </header>

      {/* --------------------------------------------------------- event */}
      <section className="moment__block">
        <p className="moment__label">{t.ws.momentEvent}</p>
        {lastEvent ? (
          <p className="moment__event">
            {fmt(t.ws.sinceEvent, {
              n: (Math.round((week - lastEvent.week) * 2) / 2).toString(),
              what: eventText(lastEvent),
            })}
          </p>
        ) : (
          <p className="moment__muted">{t.ws.nothingYet}</p>
        )}
      </section>

      {/* ----------------------------------------------------- deviation */}
      {deviations.length > 0 && (
        <section className="moment__block">
          <p className="moment__label">{t.ws.deviation}</p>
          <ul className="moment__list">
            {deviations.map((d) => (
              <li key={d.id}>
                <span>{indicatorName(t, INDICATOR_BY_ID[d.id])}</span>
                <b className="tabular" data-dir={d.delta >= 0 ? 'up' : 'down'}>
                  {d.delta >= 0 ? '+' : ''}
                  {formatValue(d.id, d.delta)}
                </b>
                <i className="moment__arrow" data-dir={d.delta >= 0 ? 'up' : 'down'} aria-hidden="true">
                  {d.delta >= 0 ? '↑' : '↓'}
                </i>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* --------------------------------------------------- attribution */}
      {contrib && contrib.rows.length > 0 && (
        <section className="moment__block">
          <p className="moment__label">{t.ws.topContribution}</p>
          <div className="moment__bars">
            {contrib.rows.map((row) => (
              <div className="moment__bar" key={row.spec}>
                <span className="moment__bar-name">{t.engine.interventions[row.spec]}</span>
                <span className="moment__bar-track" aria-hidden="true">
                  <i style={{ inlineSize: `${Math.round(row.share * 100)}%` }} data-spec={row.spec} />
                </span>
                <b className="tabular">{Math.round(row.share * 100)}%</b>
              </div>
            ))}
          </div>
          <p className="moment__note">{t.ws.attributionNote}</p>
        </section>
      )}

      {/* --------------------------------------------------------- risks */}
      {!control_ && (
        <section className="moment__block">
          <p className="moment__label">{t.ws.risks}</p>
          {risks.length === 0 ? (
            <p className="moment__muted">{t.ws.noRisk}</p>
          ) : (
            <ul className="moment__risks">
              {risks.map((r) => {
                const name = indicatorName(t, INDICATOR_BY_ID[r.indicator])
                const template =
                  r.level === 'alert'
                    ? r.side === 'high'
                      ? t.ws.riskOverHigh
                      : t.ws.riskOverLow
                    : r.side === 'high'
                      ? t.ws.riskHigh
                      : t.ws.riskLow
                return (
                  <li key={r.indicator} data-level={r.level}>
                    <span className="moment__risk-dot" aria-hidden="true" />
                    <span>{fmt(template, { name })}</span>
                    <span className="moment__risk-conf">
                      {t.ws.confidence}: {t.ws[r.confidence]}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      )}

      {/* --------------------------------------------------- divergence */}
      {why.length > 0 && (
        <section className="moment__block">
          <p className="moment__label">{t.ws.whyDiverged}</p>
          <ul className="moment__why">
            {why.map((e, i) => (
              <li key={i}>
                <span className="tabular">
                  {t.ws.week} {e.week}
                </span>
                <span>{eventText(e)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {rival && (
        <button type="button" className="moment__compare" onClick={onCompare}>
          {fmt(t.ws.compareWith, { name: label(rival) })}
        </button>
      )}
    </aside>
  )
}
