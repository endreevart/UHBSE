import { useMemo } from 'react'
import {
  INDICATOR_BY_ID,
  formatValue,
  simulate,
  type IndicatorId,
  type Scenario,
} from '../engine/model'
import { flagOf, referenceFor, type Baselines, type Subject } from '../engine/subject'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'

const GW = 96
const GH = 12

interface Props {
  scenario: Scenario
  subject: Subject
  baselines: Baselines
  week: number
  ids: IndicatorId[]
}

/**
 * The subject's vitals as gauges rather than as a column of numbers.
 *
 * A number tells you the value; it does not tell you whether the value is where
 * it should be, and that is the only question worth asking of a vital at a
 * glance. Each row carries its own reference interval, the week-0 mark and the
 * current model value, so "moving, and towards which edge" is readable without
 * reading anything.
 */
export function VitalStrip({ scenario, subject, baselines, week, ids }: Props) {
  const { t } = useI18n()

  const rows = useMemo(
    () =>
      ids.map((id) => {
        const at = Math.round(week * 2)
        const value = simulate(scenario, id, baselines).points[at]?.value ?? baselines[id]
        return { id, value, start: baselines[id] }
      }),
    [ids, scenario, baselines, week],
  )

  return (
    <ul className="vitals" data-hint={t.ws.hints.vitals}>
      {rows.map(({ id, value, start }) => {
        const indicator = INDICATOR_BY_ID[id]
        const range = referenceFor(subject, id)
        const flag = flagOf(subject, id, value)
        const delta = value - start

        // the window is wide enough to hold the interval, the start and where
        // the simulation has taken it, so a marker never runs off the gauge
        const lo = Math.min(range?.[0] ?? value, value, start)
        const hi = Math.max(range?.[1] ?? value, value, start)
        const pad = Math.max((hi - lo) * 0.18, Math.abs(hi) * 0.02, 1e-6)
        const min = lo - pad
        const max = hi + pad
        const at = (v: number) => ((v - min) / (max - min)) * GW

        return (
          <li className="vitals__row" key={id} data-flag={flag}>
            <span className="vitals__name">{indicatorName(t, indicator)}</span>

            <svg className="vitals__gauge" viewBox={`0 0 ${GW} ${GH}`} aria-hidden="true">
              <line className="vitals__track" x1={0} y1={GH / 2} x2={GW} y2={GH / 2} />
              {range && (
                <rect
                  className="vitals__band"
                  x={at(range[0])}
                  y={2}
                  width={Math.max(1, at(range[1]) - at(range[0]))}
                  height={GH - 4}
                  rx={1}
                />
              )}
              <line className="vitals__start" x1={at(start)} y1={1} x2={at(start)} y2={GH - 1} />
              <circle className="vitals__now" cx={at(value)} cy={GH / 2} r={3} />
            </svg>

            <span className="vitals__value tabular">{formatValue(id, value)}</span>
            <span className="vitals__delta tabular" data-dir={delta >= 0 ? 'up' : 'down'}>
              {Math.abs(delta) < Math.abs(start) * 0.005
                ? '—'
                : `${delta > 0 ? '+' : '−'}${formatValue(id, Math.abs(delta))}`}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
