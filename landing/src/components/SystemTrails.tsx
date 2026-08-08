import { useMemo } from 'react'
import {
  CHECKPOINTS,
  HORIZON_WEEKS,
  INDICATOR_BY_ID,
  formatValue,
  simulate,
  type IndicatorId,
  type Scenario,
} from '../engine/model'
import { attribution } from '../engine/graph'
import { smoothPath, toBand } from '../lib/curve'
import type { Baselines } from '../engine/subject'
import type { SystemLoad } from '../engine/systems'
import type { SystemId } from '../engine/indicators'
import { useI18n } from '../i18n'
import { indicatorName, systemName } from '../i18n/names'

const W = 224
const H = 86
const PAD_T = 9
const PAD_B = 15
const MAX_TRAILS = 9
/** Below this an indicator has not left its own week-to-week wobble. */
const MOVED = 0.05

type Channel = 'direct' | 'secondary'
type Row = { id: IndicatorId; sigma: number }

interface Trail {
  id: IndicatorId
  sigma: number
  indicator: (typeof INDICATOR_BY_ID)[IndicatorId]
  band: string
  inner: string
  line: string
  control: string
  ref: { y: number; h: number } | null
  nowX: number
  nowY: number
  value: number
  checks: number[]
}

/**
 * One trajectory per row, each on its own vertical scale.
 *
 * Scaling every trail to a shared axis would be meaningless — calcium and
 * vitamin D do not share units — so the grid compares the shape of a response
 * and the sigma figure in each header compares its size.
 */
function useTrails(
  rows: Row[],
  scenario: Scenario,
  control: Scenario,
  baselines: Baselines,
  week: number,
): Trail[] {
  return useMemo(
    () =>
      rows.map((row) => {
        const arm = simulate(scenario, row.id, baselines).points
        const base = simulate(control, row.id, baselines).points
        const indicator = INDICATOR_BY_ID[row.id]

        let lo = Infinity
        let hi = -Infinity
        for (let i = 0; i < arm.length; i += 1) {
          lo = Math.min(lo, arm[i].lower, base[i]?.value ?? arm[i].lower)
          hi = Math.max(hi, arm[i].upper, base[i]?.value ?? arm[i].upper)
        }
        const pad = (hi - lo) * 0.12 || 1
        lo -= pad
        hi += pad

        const x = (tw: number) => (tw / HORIZON_WEEKS) * W
        const y = (v: number) => PAD_T + (1 - (v - lo) / (hi - lo)) * (H - PAD_T - PAD_B)

        const at = Math.round(week * 2)
        const now = arm[Math.min(at, arm.length - 1)]
        const ref = indicator.reference

        return {
          id: row.id,
          sigma: row.sigma,
          indicator,
          band: toBand(
            arm.map((p) => ({ x: x(p.t), y: y(p.upper) })),
            arm.map((p) => ({ x: x(p.t), y: y(p.lower) })),
          ),
          inner: toBand(
            arm.map((p) => ({ x: x(p.t), y: y(p.innerUpper) })),
            arm.map((p) => ({ x: x(p.t), y: y(p.innerLower) })),
          ),
          line: smoothPath(arm.map((p) => ({ x: x(p.t), y: y(p.value) }))),
          control: smoothPath(base.map((p) => ({ x: x(p.t), y: y(p.value) }))),
          ref:
            ref && ref[1] > lo && ref[0] < hi
              ? {
                  y: y(Math.min(hi, ref[1])),
                  h: Math.max(1, y(Math.max(lo, ref[0])) - y(Math.min(hi, ref[1]))),
                }
              : null,
          nowX: x(now?.t ?? 0),
          nowY: y(now?.value ?? 0),
          value: now?.value ?? 0,
          checks: CHECKPOINTS.map((c) => x(c)),
        }
      }),
    [rows, scenario, control, baselines, week],
  )
}

function TrailCard({
  trail,
  on,
  armColor,
  layout = 'card',
  onSelect,
}: {
  trail: Trail
  on: boolean
  armColor: string
  layout?: 'card' | 'row'
  onSelect: (id: IndicatorId) => void
}) {
  const { t } = useI18n()
  return (
    <button
      type="button"
      className={`trail${layout === 'row' ? ' trail--row' : ''}`}
      data-on={on}
      data-dir={trail.sigma >= 0 ? 'up' : 'down'}
      onClick={() => onSelect(trail.id)}
    >
      <span className="trail__head">
        <span className="trail__name">{indicatorName(t, trail.indicator)}</span>
        <span className="trail__sigma tabular">
          {trail.sigma >= 0 ? '+' : ''}
          {trail.sigma.toFixed(1)}σ
        </span>
      </span>

      <span className="figure-ltr" dir="ltr">
        <svg className="trail__svg" viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
          {trail.ref && (
            <rect className="trail__ref" x={0} y={trail.ref.y} width={W} height={trail.ref.h} />
          )}
          {trail.checks.map((cx) => (
            <line key={cx} className="trail__check" x1={cx} y1={PAD_T - 4} x2={cx} y2={H - PAD_B} />
          ))}
          <path className="trail__band" d={trail.band} style={{ fill: armColor }} />
          <path className="trail__band trail__band--inner" d={trail.inner} style={{ fill: armColor }} />
          <path className="trail__control" d={trail.control} />
          <path className="trail__line" d={trail.line} style={{ stroke: armColor }} />
          <line className="trail__head-line" x1={trail.nowX} y1={PAD_T - 4} x2={trail.nowX} y2={H - PAD_B} />
          <circle className="trail__now" cx={trail.nowX} cy={trail.nowY} r={3.2} style={{ fill: armColor }} />
        </svg>
      </span>

      <span className="trail__foot">
        <span className="trail__value tabular">{formatValue(trail.id, trail.value)}</span>
        <span className="trail__unit">{trail.indicator.unit}</span>
      </span>
    </button>
  )
}

interface Props {
  loads: SystemLoad[]
  scenario: Scenario
  control: Scenario
  baselines: Baselines
  week: number
  channel: Channel
  armColor: string
  selectedSystem: SystemId | null
  selectedIndicator: IndicatorId | null
  onChannel: (c: Channel) => void
  onSelectIndicator: (id: IndicatorId) => void
}

/**
 * Every indicator the selected system moved, as a small trajectory.
 *
 * The panel answers "what did the protocol do here" the way the hero figure
 * does: a median line over an uncertainty band, the untreated arm dashed
 * underneath, and the reference interval as a quiet horizontal field. Reading
 * several side by side is what makes the shape of a response legible — a single
 * number at the playhead cannot distinguish a curve that is still climbing from
 * one that peaked at week eight and is falling back.
 */
export function SystemTrails({
  loads,
  scenario,
  control,
  baselines,
  week,
  channel,
  armColor,
  selectedSystem,
  selectedIndicator,
  onChannel,
  onSelectIndicator,
}: Props) {
  const { t, fmt } = useI18n()

  const current = useMemo(
    () => loads.find((l) => l.system === selectedSystem) ?? loads[0],
    [loads, selectedSystem],
  )

  // A trail that never leaves its baseline says only that the protocol does
  // not reach this indicator, which the system share above already said. Nine
  // flat lines crowd out the four that carry the answer.
  const rows = useMemo(() => {
    const all = current?.indicators ?? []
    const moved = all.filter((r) => Math.abs(r.sigma) >= MOVED)
    return (moved.length > 0 ? moved : all).slice(0, MAX_TRAILS)
  }, [current])

  const trails = useTrails(rows, scenario, control, baselines, week)

  // Ablation over the engine's additive effect terms: exact for this model.
  // Only the intended channel is attributable this way — `simulate` does not
  // carry off-target load, so claiming a per-intervention split for the
  // secondary view would be inventing a number the engine never computed.
  const credit = useMemo(
    () =>
      selectedIndicator && channel === 'direct'
        ? attribution(scenario, control, selectedIndicator, week, baselines)
        : null,
    [scenario, control, selectedIndicator, week, baselines, channel],
  )

  const creditRows = credit?.rows.filter((r) => Math.abs(r.value) > 0) ?? []

  return (
    <section className="trails" data-hint={t.ws.hints.trails}>
      <header className="pane__head">
        <h3 className="pane__title">
          {current ? systemName(t, current.system) : t.ws.bodyTitle}
          <span className="trails__sub">
            {fmt(t.ws.bodyTitle, { n: Math.round(week * 2) / 2 })}
          </span>
        </h3>
        <div className="pane__tabs" data-hint={t.ws.hints.channel}>
          <button
            type="button"
            className="pane__tab"
            data-on={channel === 'direct'}
            onClick={() => onChannel('direct')}
          >
            {t.ws.direct}
          </button>
          <button
            type="button"
            className="pane__tab"
            data-on={channel === 'secondary'}
            onClick={() => onChannel('secondary')}
          >
            {t.ws.secondary}
          </button>
        </div>
      </header>

      <div className="trails__grid">
        {trails.map((trail) => (
          <TrailCard
            key={trail.id}
            trail={trail}
            on={trail.id === selectedIndicator}
            armColor={armColor}
            onSelect={onSelectIndicator}
          />
        ))}
        {trails.length === 0 && <p className="pane__empty">{t.ws.bodyPick}</p>}
      </div>

      <div className="trails__foot">
        {selectedIndicator && creditRows.length > 0 ? (
          <div className="trails__credit">
            <span className="mono-label">{t.ws.topContribution}</span>
            {creditRows.map((row) => (
              <span key={row.spec} className="trails__credit-item">
                <span className="trails__credit-name">{t.engine.interventions[row.spec]}</span>
                <span className="trails__credit-bar">
                  <i style={{ width: `${Math.round(row.share * 100)}%` }} />
                </span>
                <span className="trails__credit-share tabular">{Math.round(row.share * 100)}%</span>
              </span>
            ))}
          </div>
        ) : (
          <span className="bodymap__read">
            {channel === 'direct' ? t.ws.bodyPick : t.ws.secondaryNote}
          </span>
        )}
        <span className="bodymap__note">{t.ws.attributionNote}</span>
      </div>
    </section>
  )
}

/**
 * Everything else the protocol moved, outside the system currently open.
 *
 * The system bar says a protocol is landing on seven systems at once and then
 * the column below shows one of them, which leaves the other six as a number
 * with nothing behind it. This is the rest of that answer, and it fills the
 * height the protocol rail would otherwise leave empty.
 */
export function OtherTrails({
  loads,
  scenario,
  control,
  baselines,
  week,
  armColor,
  exclude,
  selectedIndicator,
  onSelectIndicator,
}: {
  loads: SystemLoad[]
  scenario: Scenario
  control: Scenario
  baselines: Baselines
  week: number
  armColor: string
  exclude: SystemId | null
  selectedIndicator: IndicatorId | null
  onSelectIndicator: (id: IndicatorId) => void
}) {
  const { t } = useI18n()

  const groups = useMemo(
    () =>
      loads
        .filter((l) => l.system !== exclude)
        .map((l) => ({
          system: l.system,
          rows: l.indicators.filter((r) => Math.abs(r.sigma) >= MOVED).slice(0, MAX_TRAILS),
        }))
        .filter((g) => g.rows.length > 0),
    [loads, exclude],
  )

  const flat = useMemo(() => groups.flatMap((g) => g.rows), [groups])
  const trails = useTrails(flat, scenario, control, baselines, week)
  const byId = useMemo(() => new Map(trails.map((tr) => [tr.id, tr])), [trails])

  if (groups.length === 0) return null

  return (
    <section className="trails trails--rest">
      <header className="pane__head">
        <h3 className="pane__title">{t.ws.otherSystems}</h3>
      </header>

      <div
        className="trails__rest-columns"
        style={{ ['--trail-cols' as string]: groups.length }}
      >
        {groups.map((group) => (
          <div className="trails__column" key={group.system}>
            <p className="mono-label trails__group">{systemName(t, group.system)}</p>
            <div className="trails__stack">
              {group.rows.map((row) => {
                const trail = byId.get(row.id)
                return trail ? (
                  <TrailCard
                    key={row.id}
                    trail={trail}
                    layout="row"
                    on={row.id === selectedIndicator}
                    armColor={armColor}
                    onSelect={onSelectIndicator}
                  />
                ) : null
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
