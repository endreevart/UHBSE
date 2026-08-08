import { useMemo, useRef } from 'react'
import {
  CHECKPOINTS,
  CONTROL_COLOR,
  HORIZON_WEEKS,
  INDICATOR_BY_ID,
  INTERVENTIONS,
  SCENARIO_COLORS,
  formatValue,
  isControl,
  simulate,
  type IndicatorId,
  type Scenario,
} from '../engine/model'
import { smoothPath, toBand } from '../lib/curve'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'

const W = 820
const H = 430
const PAD_L = 48
const PAD_R = 70
const PAD_T = 22
const PAD_B = 46

export const armColor = (s: Scenario) =>
  isControl(s) ? CONTROL_COLOR : SCENARIO_COLORS[s.colorIndex % SCENARIO_COLORS.length]

interface Props {
  scenarios: Scenario[]
  /** the subject's starting values; without them every chart describes nobody */
  baselines: Partial<Record<IndicatorId, number>>
  indicatorId: IndicatorId
  cursorWeek: number
  activeScenarioId: string
  onCursorChange: (week: number) => void
}

/** Nice round tick steps so the scale reads like an instrument, not like a float dump. */
function niceTicks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v)
  return out
}

export function EngineChart({
  scenarios,
  baselines,
  indicatorId,
  cursorWeek,
  activeScenarioId,
  onCursorChange,
}: Props) {
  const { t, fmt } = useI18n()
  const svgRef = useRef<SVGSVGElement>(null)
  const indicator = INDICATOR_BY_ID[indicatorId]

  const computed = useMemo(
    () => scenarios.map((s) => ({ scenario: s, series: simulate(s, indicatorId, baselines) })),
    [scenarios, indicatorId, baselines],
  )
  const active = computed.find(({ scenario }) => scenario.id === activeScenarioId) ?? computed[0]

  // only the active arm shows a filled band, so the scale is driven by it plus
  // every median line — otherwise four stacked 95% bands blow the axis apart
  const domain = useMemo(() => {
    let lo = Infinity
    let hi = -Infinity
    for (const { scenario, series } of computed) {
      const isActive = scenario.id === activeScenarioId
      for (const p of series.points) {
        lo = Math.min(lo, isActive ? p.lower : p.value)
        hi = Math.max(hi, isActive ? p.upper : p.value)
      }
    }
    if (indicator.reference) {
      lo = Math.min(lo, indicator.reference[0])
      hi = Math.max(hi, indicator.reference[1])
    }
    const pad = (hi - lo) * 0.12 || 1
    return [Math.max(0, lo - pad), hi + pad] as const
  }, [computed, indicator, activeScenarioId])

  const x = (week: number) => PAD_L + (week / HORIZON_WEEKS) * (W - PAD_L - PAD_R)
  const y = (value: number) =>
    PAD_T + (1 - (value - domain[0]) / (domain[1] - domain[0])) * (H - PAD_T - PAD_B)

  const yTicks = useMemo(() => niceTicks(domain[0], domain[1], 5), [domain])
  const plotR = W - PAD_R
  const plotB = H - PAD_B

  const handlePointer = (event: React.PointerEvent<SVGRectElement>) => {
    if (event.type === 'pointermove' && event.buttons === 0) return
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const px = ((event.clientX - rect.left) / rect.width) * W
    const week = ((px - PAD_L) / (W - PAD_L - PAD_R)) * HORIZON_WEEKS
    onCursorChange(Math.max(0, Math.min(HORIZON_WEEKS, Math.round(week * 2) / 2)))
  }

  // readout labels are stacked to the right of the plot; nudge them apart so two
  // arms sitting on the same value stay legible
  const readouts = computed
    .map(({ scenario, series }) => ({
      scenario,
      point: series.points[Math.round(cursorWeek * 2)],
    }))
    .sort((a, b) => a.point.value - b.point.value)
  const labelY: number[] = []
  for (let i = readouts.length - 1; i >= 0; i -= 1) {
    const wanted = y(readouts[i].point.value)
    const below = labelY[0]
    labelY.unshift(below === undefined ? wanted : Math.min(wanted, below - 13))
  }

  return (
    <div className="figure-ltr" dir="ltr">
      <svg
        ref={svgRef}
        className="lab-chart"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`${indicatorName(t, indicator)} — ${t.engine.title}`}
      >
        <defs>
          <clipPath id="lab-plot">
            <rect x={PAD_L} y={PAD_T} width={plotR - PAD_L} height={plotB - PAD_T} />
          </clipPath>
        </defs>

        {/* reference interval: the clinical corridor this indicator should stay in */}
        {indicator.reference && (
          <g className="lab-ref">
            <rect
              x={PAD_L}
              y={y(indicator.reference[1])}
              width={plotR - PAD_L}
              height={Math.max(0, y(indicator.reference[0]) - y(indicator.reference[1]))}
            />
            {indicator.reference.map((v) => (
              <line key={v} x1={PAD_L} y1={y(v)} x2={plotR} y2={y(v)} />
            ))}
            <text className="lab-ref-label" x={PAD_L + 6} y={y(indicator.reference[1]) - 5}>
              {t.engine.refLabel} {formatValue(indicatorId, indicator.reference[0])}–
              {formatValue(indicatorId, indicator.reference[1])}
            </text>
          </g>
        )}

        <g className="lab-grid">
          {yTicks.map((v) => (
            <line key={`y${v}`} x1={PAD_L} y1={y(v)} x2={plotR} y2={y(v)} />
          ))}
          {[6, 12, 18, 24, 30].map((wk) => (
            <line key={`x${wk}`} x1={x(wk)} y1={PAD_T} x2={x(wk)} y2={plotB} />
          ))}
        </g>

        {/* scales sit outside the plot frame, with real tick marks */}
        <g className="lab-frame">
          <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={plotB} />
          <line x1={PAD_L} y1={plotB} x2={plotR} y2={plotB} />
        </g>
        {yTicks.map((v) => (
          <g key={`yt${v}`}>
            <line className="lab-frame" x1={PAD_L - 5} y1={y(v)} x2={PAD_L} y2={y(v)} />
            <text className="lab-tick" x={PAD_L - 10} y={y(v) + 3.5} textAnchor="end">
              {formatValue(indicatorId, v)}
            </text>
          </g>
        ))}
        <text className="lab-axis-name" x={PAD_L - 10} y={PAD_T - 8} textAnchor="end">
          {indicator.unit}
        </text>
        {[0, 6, 12, 18, 24, 30, 36].map((wk) => (
          <g key={`xt${wk}`}>
            <line className="lab-frame" x1={x(wk)} y1={plotB} x2={x(wk)} y2={plotB + 5} />
            <text className="lab-tick" x={x(wk)} y={plotB + 18} textAnchor="middle">
              {wk}
            </text>
          </g>
        ))}
        <text className="lab-axis-name" x={plotR} y={plotB + 30} textAnchor="end">
          {t.hero.figure.time} · {t.engine.weekShort}
        </text>

        <g clipPath="url(#lab-plot)">
          {CHECKPOINTS.map((wk) => (
            <line key={`cp${wk}`} className="lab-checkpoint" x1={x(wk)} y1={PAD_T} x2={x(wk)} y2={plotB} />
          ))}

          {/* active arm only: 95% as bare outlines, 68% as the one filled band —
              filling both turns the plot into a single opaque wedge */}
          {active && (
            <g>
              <path
                className="lab-band lab-band--inner"
                d={toBand(
                  active.series.points.map((p) => ({ x: x(p.t), y: y(p.innerUpper) })),
                  active.series.points.map((p) => ({ x: x(p.t), y: y(p.innerLower) })),
                )}
                style={{ fill: armColor(active.scenario) }}
              />
              {(['upper', 'lower'] as const).map((edge) => (
                <path
                  key={edge}
                  className="lab-band-edge"
                  d={smoothPath(active.series.points.map((p) => ({ x: x(p.t), y: y(p[edge]) })))}
                  style={{ stroke: armColor(active.scenario) }}
                />
              ))}
            </g>
          )}

          {/* every median: control dashed and grey, arms as thin phosphor lines */}
          {computed.map(({ scenario, series }) => {
            const color = armColor(scenario)
            const isActive = scenario.id === activeScenarioId
            const d = smoothPath(
              series.points.filter((_, i) => i % 2 === 0).map((p) => ({ x: x(p.t), y: y(p.value) })),
            )
            return (
              <g key={`mid-${scenario.id}`}>
                <path
                  className="lab-line-glow"
                  d={d}
                  opacity={isActive ? 0.5 : 0.2}
                  style={{ stroke: color }}
                />
                <path
                  className="lab-line"
                  d={d}
                  strokeWidth={isActive ? 1.8 : 1.1}
                  strokeDasharray={isControl(scenario) ? '5 4' : undefined}
                  opacity={isActive ? 1 : 0.72}
                  style={{ stroke: color }}
                />
              </g>
            )
          })}

          {/* where an arm leaves the control */}
          {computed
            .filter(({ scenario }) => scenario.branchWeek > 0)
            .map(({ scenario, series }) => (
              <circle
                key={`bp-${scenario.id}`}
                className="lab-branch"
                cx={x(scenario.branchWeek)}
                cy={y(series.points[Math.round(scenario.branchWeek * 2)].value)}
                r="3.6"
                style={{ stroke: armColor(scenario) }}
              />
            ))}

          {computed.map(({ scenario, series }) =>
            series.checkpoints.map((cp) => (
              <circle
                key={`${scenario.id}-cp-${cp.t}`}
                className="lab-cp-dot"
                cx={x(cp.t)}
                cy={y(cp.value)}
                r="2.8"
                opacity={scenario.id === activeScenarioId ? 1 : 0.45}
                style={{ stroke: armColor(scenario) }}
              />
            )),
          )}
        </g>

        {CHECKPOINTS.map((wk) => (
          <text key={`cpl${wk}`} className="lab-tick lab-tick--dim" x={x(wk)} y={PAD_T - 10} textAnchor="middle">
            {t.engine.weekShort} {wk}
          </text>
        ))}

        {/* interventions of the active arm, marked on the time axis */}
        {active?.scenario.interventions
          .filter((iv) => iv.dose > 0 && iv.endWeek === undefined)
          .map((iv, i) => {
            const at = x(iv.startWeek)
            // flip the label inward once the marker is past the middle, otherwise
            // late interventions write over the readout column
            const flip = at > (PAD_L + plotR) / 2
            return (
              <g key={`iv-${iv.key}`}>
                <line className="lab-intervention" x1={at} y1={PAD_T} x2={at} y2={plotB} />
                <polygon
                  className="lab-iv-flag"
                  points={`${at},${plotB} ${at - 4},${plotB + 7} ${at + 4},${plotB + 7}`}
                />
                <text
                  className="lab-iv-label"
                  x={flip ? at - 6 : at + 6}
                  y={PAD_T + 11 + i * 12}
                  textAnchor={flip ? 'end' : 'start'}
                >
                  {t.engine.interventions[INTERVENTIONS[iv.spec].id]}
                </text>
              </g>
            )
          })}

        {/* playhead */}
        <line className="lab-cursor" x1={x(cursorWeek)} y1={PAD_T} x2={x(cursorWeek)} y2={plotB + 6} />
        {readouts.map(({ scenario, point }, i) => (
          <g key={`cur-${scenario.id}`}>
            <circle
              className="lab-cur-dot"
              cx={x(cursorWeek)}
              cy={y(point.value)}
              r="3.2"
              style={{ fill: armColor(scenario) }}
            />
            {/* short jog outside the frame; a lead drawn from the playhead would
                cut a long diagonal straight across the plot */}
            <polyline
              className="lab-readout-lead"
              points={`${plotR},${y(point.value)} ${plotR + 5},${y(point.value)} ${plotR + 9},${labelY[i]}`}
              style={{ stroke: armColor(scenario) }}
            />
            <text
              className="lab-readout"
              x={plotR + 12}
              y={labelY[i] + 3.5}
              style={{ fill: armColor(scenario) }}
            >
              {formatValue(indicatorId, point.value)}
            </text>
          </g>
        ))}
        <text className="lab-tick lab-tick--cursor" x={x(cursorWeek)} y={plotB + 28} textAnchor="middle">
          {fmt(t.hero.figure.week, { n: cursorWeek })}
        </text>

        <rect
          className="lab-hit"
          x={PAD_L}
          y={PAD_T}
          width={plotR - PAD_L}
          height={plotB - PAD_T}
          onPointerDown={handlePointer}
          onPointerMove={handlePointer}
        />
      </svg>
    </div>
  )
}
