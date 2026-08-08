import { Fragment, useMemo, useState } from 'react'
import {
  INDICATOR_BY_ID,
  INTERVENTIONS,
  formatValue,
  isControl,
  simulate,
  type IndicatorId,
  type Scenario,
} from '../engine/model'
import { attribution, protocolDiff, type BranchStatus, type ProtocolEvent } from '../engine/graph'
import type { Baselines } from '../engine/subject'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'
import { armColor } from './EngineChart'

interface Props {
  scenarios: Scenario[]
  control: Scenario
  baselines: Baselines
  status: Map<string, BranchStatus>
  panel: IndicatorId[]
  totalIndicators: number
  week: number
  selectedId: string
  label: (s: Scenario) => string
  summary: (s: Scenario) => string
  eventText: (e: ProtocolEvent) => string
  onSelect: (id: string) => void
  onOpenAll: () => void
}

/**
 * Every branch, every indicator, at the week on the playhead.
 *
 * The old table compared arms at fixed checkpoints, which meant scrubbing the
 * timeline moved the chart but left the numbers underneath it describing a
 * different moment. Reading the matrix at the cursor is what makes the whole
 * workspace one instrument rather than several.
 */
export function CompareMatrix({
  scenarios,
  control,
  baselines,
  status,
  panel,
  totalIndicators,
  week,
  selectedId,
  label,
  summary,
  eventText,
  onSelect,
  onOpenAll,
}: Props) {
  const { t, fmt } = useI18n()
  const [open, setOpen] = useState<IndicatorId | null>(null)

  const columns = useMemo(
    () => [control, ...scenarios.filter((s) => !isControl(s))],
    [scenarios, control],
  )

  // one pass over branch × indicator, held together so a scrub does not
  // re-simulate the same branch once per row
  const cells = useMemo(() => {
    const at = Math.round(week * 2)
    return columns.map((s) => {
      const stop = status.get(s.id)?.stopWeek ?? -1
      const idx = stop >= 0 && week > stop ? stop * 2 : at
      const ctrlStop = status.get(control.id)?.stopWeek ?? -1
      const ctrlIdx = ctrlStop >= 0 && week > ctrlStop ? ctrlStop * 2 : at
      return panel.map((id) => {
        const p = simulate(s, id, baselines).points[idx]
        const base = simulate(control, id, baselines).points[ctrlIdx].value
        return { id, value: p.value, lower: p.lower, upper: p.upper, delta: p.value - base }
      })
    })
  }, [columns, control, panel, baselines, week, status])

  const reasons = useMemo(
    () => panel.map((id) => reasonFor(id, columns, control, week)),
    [panel, columns, control, week],
  )

  return (
    <section className="matrix" data-hint={t.ws.hints.matrix}>
      <header className="pane__head">
        <h3 className="pane__title">{fmt(t.ws.cmpTitle, { n: Math.round(week * 2) / 2 })}</h3>
        <button type="button" className="matrix__all" onClick={onOpenAll}>
          {fmt(t.ws.cmpOpenAll, { n: totalIndicators })}
        </button>
      </header>

      <div className="matrix__scroll">
        <table className="matrix__table">
          <thead>
            <tr>
              <th className="matrix__corner">{t.ws.cmpIndicator}</th>
              {columns.map((s) => {
                const stopped = (status.get(s.id)?.stopWeek ?? -1) >= 0
                return (
                  <th
                    key={s.id}
                    data-active={s.id === selectedId}
                    data-stopped={stopped}
                    style={{ ['--sc' as string]: isControl(s) ? 'var(--arm-control)' : armColor(s) }}
                  >
                    <button type="button" className="matrix__pick" onClick={() => onSelect(s.id)}>
                      <span className="matrix__dot" />
                      <span className="matrix__name">{label(s)}</span>
                      <span className="matrix__sub">{summary(s)}</span>
                    </button>
                  </th>
                )
              })}
              <th className="matrix__why">{t.ws.cmpReason}</th>
            </tr>
          </thead>
          <tbody>
            {panel.map((id, row) => (
              <Fragment key={id}>
              <tr data-open={open === id}>
                <th scope="row">
                  <button
                    type="button"
                    className="matrix__row-open"
                    aria-expanded={open === id}
                    onClick={() => setOpen(open === id ? null : id)}
                  >
                    <span className="matrix__ind">{indicatorName(t, INDICATOR_BY_ID[id])}</span>
                    <span className="matrix__unit">{INDICATOR_BY_ID[id].unit}</span>
                  </button>
                </th>
                {columns.map((s, col) => {
                  const cell = cells[col][row]
                  const control_ = isControl(s)
                  return (
                    <td key={s.id} data-active={s.id === selectedId} className="tabular">
                      <span className="matrix__value">{formatValue(id, cell.value)}</span>
                      {!control_ && Math.abs(cell.delta) > 1e-9 && (
                        <span className="matrix__delta" data-dir={cell.delta >= 0 ? 'up' : 'down'}>
                          {cell.delta >= 0 ? '+' : ''}
                          {formatValue(id, cell.delta)}
                          {cell.delta >= 0 ? ' ↑' : ' ↓'}
                        </span>
                      )}
                      <span className="matrix__range">
                        {formatValue(id, cell.lower)} – {formatValue(id, cell.upper)}
                      </span>
                    </td>
                  )
                })}
                <td className="matrix__why">
                  {reasons[row].map((e, i) => (
                    <span key={i} className="matrix__reason">
                      <b className="tabular">
                        {t.ws.week} {e.week}
                      </b>
                      {eventText(e)}
                    </span>
                  ))}
                </td>
              </tr>

              {/* the split opens under the row it explains rather than in a
                  panel elsewhere: the numbers being accounted for stay on
                  screen while the account is read */}
              {open === id && (
                <tr className="matrix__detail">
                  <td colSpan={columns.length + 2}>
                    <div className="matrix__breakdown">
                      {columns
                        .filter((s) => !isControl(s))
                        .map((s) => (
                          <Breakdown
                            key={s.id}
                            scenario={s}
                            control={control}
                            baselines={baselines}
                            indicatorId={id}
                            week={week}
                            name={label(s)}
                            colour={armColor(s)}
                          />
                        ))}
                    </div>
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <p className="matrix__note">
        {t.ws.cmpNote} {t.ws.cmpUnits}
      </p>
    </section>
  )
}

/**
 * One branch's share of the movement in one indicator.
 *
 * The matrix says the branches differ; this says which part of each protocol is
 * doing it. The residual is printed rather than absorbed: while the model stays
 * additive it is ~0, and the moment it stops being ~0 the panel should be the
 * thing that says so.
 */
function Breakdown({
  scenario,
  control,
  baselines,
  indicatorId,
  week,
  name,
  colour,
}: {
  scenario: Scenario
  control: Scenario
  baselines: Baselines
  indicatorId: IndicatorId
  week: number
  name: string
  colour: string
}) {
  const { t } = useI18n()
  const credit = useMemo(
    () => attribution(scenario, control, indicatorId, week, baselines),
    [scenario, control, indicatorId, week, baselines],
  )

  return (
    <div className="brk" style={{ ['--sc' as string]: colour }}>
      <header className="brk__head">
        <i className="brk__dot" />
        <span className="brk__name">{name}</span>
        <span className="brk__total tabular" data-dir={credit.total >= 0 ? 'up' : 'down'}>
          {credit.total >= 0 ? '+' : ''}
          {formatValue(indicatorId, credit.total)}
        </span>
      </header>

      {credit.rows.length === 0 ? (
        <p className="brk__empty">{t.ws.noContribution}</p>
      ) : (
        <ul className="brk__list">
          {credit.rows.map((row) => (
            <li className="brk__row" key={row.spec}>
              <span className="brk__spec">{t.engine.interventions[row.spec]}</span>
              <span className="brk__bar" aria-hidden="true">
                <i style={{ inlineSize: `${Math.round(row.share * 100)}%` }} />
              </span>
              <span className="brk__value tabular" data-dir={row.value >= 0 ? 'up' : 'down'}>
                {row.value >= 0 ? '+' : ''}
                {formatValue(indicatorId, row.value)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Which protocol changes are responsible for the spread across a row.
 *
 * Only the interventions that actually touch this indicator count: a nutrition
 * change is not the reason TSH differs between two branches, even though it is
 * the reason those branches exist.
 */
function reasonFor(
  id: IndicatorId,
  columns: Scenario[],
  control: Scenario,
  week: number,
): ProtocolEvent[] {
  const seen = new Map<string, ProtocolEvent>()
  for (const s of columns) {
    if (isControl(s)) continue
    for (const event of protocolDiff(s, control, week)) {
      const spec = event.spec
      // the effects table is the only honest filter here: it is what the
      // simulation actually uses to move this analyte
      const touches = INTERVENTIONS[spec].effects[id] !== undefined
      if (!touches) continue
      const key = `${event.week}:${spec}:${event.kind}`
      if (!seen.has(key)) seen.set(key, event)
    }
  }
  return [...seen.values()].sort((a, b) => a.week - b.week).slice(0, 2)
}
