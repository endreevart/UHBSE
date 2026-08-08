import { memo, useMemo } from 'react'
import {
  HORIZON_WEEKS,
  SIGMA_CLAMP,
  SYSTEM_COLUMNS,
  type EffectRow,
  type IndicatorId,
  type SystemId,
} from '../engine/model'
import { useI18n } from '../i18n'
import { indicatorName, systemName } from '../i18n/names'
import type { Dict } from '../i18n/locales/en'

const ROW_H = 12
const GROUP_H = 22
const GROUP_GAP = 6
const LABEL_W = 124
const CELL_W = 372
const AXIS_H = 20
const VIEW_W = LABEL_W + CELL_W

/** Amber above the control, cyan below it — direction, not judgement. */
const UP = 'lab-heat-cell lab-heat-cell--up'
const DOWN = 'lab-heat-cell lab-heat-cell--down'

const xOf = (week: number) => LABEL_W + (week / HORIZON_WEEKS) * CELL_W
const TICKS = [0, 6, 12, 18, 24, 30, 36]

interface Placed {
  kind: 'group' | 'row'
  y: number
  system?: SystemId
  row?: EffectRow
}

interface Column {
  items: Placed[]
  height: number
}

interface Props {
  rows: EffectRow[]
  cursorWeek: number
  selectedId: IndicatorId
  armLabel: string
  armColor: string
  onSelect: (id: IndicatorId) => void
}

/**
 * Every indicator against the control on one timeline.
 *
 * Small multiples answer "what happened to this analyte" and stop working past
 * a dozen panels. At seventy the question becomes "what did this protocol touch
 * at all", and the only encoding that fits that many rows on one screen is a
 * colour ramp: one row per indicator, one column per week, colour as the
 * distance from the untreated arm in units of the model's own sigma.
 */
export function EffectHeatmap({
  rows,
  cursorWeek,
  selectedId,
  armLabel,
  armColor,
  onSelect,
}: Props) {
  const { t, fmt } = useI18n()

  const columns = useMemo<Column[]>(() => {
    const bySystem = new Map<SystemId, EffectRow[]>()
    for (const row of rows) {
      const list = bySystem.get(row.indicator.system) ?? []
      list.push(row)
      bySystem.set(row.indicator.system, list)
    }

    const lay = (systems: SystemId[], gap: number) => {
      const items: Placed[] = []
      let y = 0
      for (const system of systems) {
        // loudest analytes first, so the top of a group is enough to tell
        // whether the protocol reached that system at all
        const members = [...(bySystem.get(system) ?? [])].sort((a, b) => b.peak - a.peak)
        items.push({ kind: 'group', y, system })
        y += GROUP_H
        for (const row of members) {
          items.push({ kind: 'row', y, row })
          y += ROW_H
        }
        y += gap
      }
      return { items, height: y - gap }
    }

    // every column's week axis has to land on the same line, or the three stacks
    // read as three unrelated charts. Shorter columns absorb the difference into
    // their group spacing instead of trailing off into a block of empty space.
    const natural = SYSTEM_COLUMNS.map((systems) => lay(systems, GROUP_GAP))
    const height = Math.max(...natural.map((c) => c.height))
    return SYSTEM_COLUMNS.map((systems, i) => {
      const slack = height - natural[i].height
      const gaps = Math.max(1, systems.length - 1)
      return { ...lay(systems, GROUP_GAP + slack / gaps), height }
    })
  }, [rows])

  const cursorLeft = (xOf(cursorWeek) / VIEW_W) * 100

  return (
    <div className="lab__heatmap">
      <header className="lab__panel-head">
        <h3 className="lab__panel-title">{t.engine.heatmapTitle}</h3>
        <span className="mono-label">{fmt(t.engine.heatmapNote, { n: rows.length })}</span>
      </header>

      <div className="lab__heat-scale">
        <span className="lab__heat-arm">
          <span className="lab__scenario-dot" style={{ ['--sc' as string]: armColor }} />
          {armLabel}
        </span>
        <span className="lab__heat-ramp">
          <span className="mono-label">
            −{SIGMA_CLAMP}σ · {t.engine.heatmapBelow}
          </span>
          <span className="lab__heat-bar" aria-hidden="true" />
          <span className="mono-label">
            +{SIGMA_CLAMP}σ · {t.engine.heatmapAbove}
          </span>
        </span>
      </div>

      <div className="lab__heat-columns">
        {columns.map((column, ci) => (
          <div className="lab__heat-column figure-ltr" dir="ltr" key={ci}>
            <HeatColumn column={column} selectedId={selectedId} onSelect={onSelect} t={t} />
            {/* the playhead lives outside the SVG: it moves every frame and the
                cell grid behind it must not re-render with it */}
            <span
              className="lab__heat-cursor"
              aria-hidden="true"
              style={{
                left: `${cursorLeft}%`,
                height: `${(column.height / (column.height + AXIS_H)) * 100}%`,
              }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

interface ColumnProps {
  column: Column
  selectedId: IndicatorId
  onSelect: (id: IndicatorId) => void
  t: Dict
}

const HeatColumn = memo(function HeatColumn({ column, selectedId, onSelect, t }: ColumnProps) {
  return (
    <svg
      className="lab__heat-svg"
      viewBox={`0 0 ${VIEW_W} ${column.height + AXIS_H}`}
      role="img"
      aria-label={t.engine.heatmapTitle}
    >
      {column.items.map((item) =>
        item.kind === 'group' ? (
          <g key={`g-${item.system}`}>
            <text className="lab-heat-group" x={0} y={item.y + 13}>
              {systemName(t, item.system!)}
            </text>
            <line
              className="lab-heat-rule"
              x1={0}
              y1={item.y + GROUP_H - 5}
              x2={VIEW_W}
              y2={item.y + GROUP_H - 5}
            />
          </g>
        ) : (
          <HeatRow
            key={item.row!.indicator.id}
            row={item.row!}
            y={item.y}
            label={indicatorName(t, item.row!.indicator)}
            selected={item.row!.indicator.id === selectedId}
            onSelect={onSelect}
          />
        ),
      )}

      <line
        className="lab-heat-axis"
        x1={LABEL_W}
        y1={column.height + 1}
        x2={VIEW_W}
        y2={column.height + 1}
      />
      {TICKS.map((week) => (
        <text
          key={week}
          className="lab-heat-tick"
          x={xOf(week)}
          y={column.height + 14}
          textAnchor={week === 0 ? 'start' : week === HORIZON_WEEKS ? 'end' : 'middle'}
        >
          {week}
        </text>
      ))}
      <text className="lab-heat-axis-name" x={0} y={column.height + 14}>
        {t.engine.weekAxis}
      </text>
    </svg>
  )
})

interface RowProps {
  row: EffectRow
  y: number
  label: string
  selected: boolean
  onSelect: (id: IndicatorId) => void
}

/** Quantisation steps of the colour ramp; also how many paths a row can cost. */
const LEVELS = 16

/**
 * One path per (direction, intensity) step, with consecutive weeks merged into a
 * single subpath.
 *
 * Drawing a rect per week looks obvious and is wrong: neighbouring translucent
 * rects leave antialiased hairlines, so a smooth ramp renders as a striped one.
 * Merged runs share a single fill and only break where the intensity genuinely
 * steps.
 */
function runsOf(weekly: number[]): { className: string; opacity: number; d: string }[] {
  const buckets = new Map<string, number[]>()
  for (let k = 0; k < weekly.length - 1; k += 1) {
    const e = weekly[k + 1]
    const mag = Math.min(1, Math.abs(e) / SIGMA_CLAMP)
    // gentle compression: a linear ramp washes out everything under one sigma,
    // a square-root one makes a negligible effect look decisive
    const level = Math.round(Math.pow(mag, 0.75) * LEVELS)
    if (level === 0) continue
    const key = `${e > 0 ? 'u' : 'd'}${level}`
    const list = buckets.get(key)
    if (list) list.push(k)
    else buckets.set(key, [k])
  }

  const h = ROW_H - 2
  return [...buckets].map(([key, cells]) => {
    let d = ''
    for (let i = 0; i < cells.length; ) {
      let j = i
      while (j + 1 < cells.length && cells[j + 1] === cells[j] + 1) j += 1
      const x0 = xOf(cells[i])
      const w = xOf(cells[j] + 1) - x0
      d += `M${x0.toFixed(2)} 0h${w.toFixed(2)}v${h}h${(-w).toFixed(2)}z`
      i = j + 1
    }
    const level = Number(key.slice(1))
    return {
      className: key[0] === 'u' ? UP : DOWN,
      opacity: 0.08 + 0.92 * (level / LEVELS),
      d,
    }
  })
}

function HeatRow({ row, y, label, selected, onSelect }: RowProps) {
  const runs = useMemo(() => runsOf(row.weekly), [row.weekly])

  return (
    <g
      className="lab-heat-row"
      data-selected={selected}
      onClick={() => onSelect(row.indicator.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect(row.indicator.id)
      }}
    >
      <rect className="lab-heat-hit" x={0} y={y} width={VIEW_W} height={ROW_H} />
      <text className="lab-heat-label" x={0} y={y + ROW_H - 3.5}>
        {label}
      </text>

      <g transform={`translate(0 ${y + 1})`}>
        {runs.map((run, i) => (
          <path key={i} className={run.className} d={run.d} opacity={run.opacity} />
        ))}
      </g>
    </g>
  )
}
