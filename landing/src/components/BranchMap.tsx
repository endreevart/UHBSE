import { useMemo } from 'react'
import {
  HORIZON_WEEKS,
  INDICATOR_BY_ID,
  formatValue,
  isControl,
  simulate,
  type IndicatorId,
  type Scenario,
} from '../engine/model'
import {
  branchTree,
  divergence,
  type BranchNode,
  type BranchStatus,
  type ProtocolEvent,
} from '../engine/graph'
import type { Baselines } from '../engine/subject'
import { useElementWidth } from '../lib/useElementWidth'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'
import { armColor } from './EngineChart'

const PAD_L = 92
const PAD_R = 150
const PAD_T = 30
const ROW_H = 62
const PAD_B = 22
/** below this the branch labels collide, so the pane scrolls instead */
const MIN_W = 720

interface Props {
  scenarios: Scenario[]
  control: Scenario
  baselines: Baselines
  status: Map<string, BranchStatus>
  /** the three analytes shown as a readout on every branch */
  readout: IndicatorId[]
  cursorWeek: number
  selectedId: string
  activeCount: number
  stoppedCount: number
  label: (s: Scenario) => string
  eventText: (e: ProtocolEvent) => string
  onSelect: (id: string) => void
}

/**
 * The branch map.
 *
 * This is the object the whole workspace is arranged around. Everywhere else a
 * branch is a line on a chart, which makes it look like a result; here it is a
 * path — where it left its parent, which change in the protocol sent it there,
 * how far it has moved by the current week, and what eventually ends it.
 *
 * Time runs left to right on the same axis as every other view, so a branch
 * point sits at the week it actually happened rather than at an arbitrary
 * position in a diagram.
 */
export function BranchMap({
  scenarios,
  control,
  baselines,
  status,
  readout,
  cursorWeek,
  selectedId,
  activeCount,
  stoppedCount,
  label,
  eventText,
  onSelect,
}: Props) {
  const { t, fmt } = useI18n()
  const tree = useMemo(() => branchTree(scenarios), [scenarios])
  const rowOf = useMemo(
    () => new Map(tree.flat.map((n) => [n.scenario.id, n.row])),
    [tree],
  )

  const height = PAD_T + tree.rows * ROW_H + PAD_B
  // the map is built at the pane's own width so the horizon spans it at 1:1,
  // rather than being drawn at a fixed size and then centred or scaled
  const { ref: scrollRef, width: paneW } = useElementWidth<HTMLDivElement>(1000)
  const width = Math.max(MIN_W, paneW)
  const plotW = width - PAD_L - PAD_R
  const x = (w: number) => PAD_L + (w / HORIZON_WEEKS) * plotW
  const y = (row: number) => PAD_T + row * ROW_H + ROW_H / 2

  // readouts are taken once per branch per week rather than per cell: three
  // analytes across five branches is fifteen simulate() calls otherwise
  const readouts = useMemo(() => {
    const at = Math.round(cursorWeek * 2)
    const map = new Map<string, { id: IndicatorId; delta: number }[]>()
    const ctrl = readout.map((id) => simulate(control, id, baselines).points[at].value)
    for (const node of tree.flat) {
      if (isControl(node.scenario)) continue
      const stop = status.get(node.scenario.id)?.stopWeek ?? -1
      // a stopped branch holds its last value: reading past the stop would
      // report a future it never had
      const idx = stop >= 0 && cursorWeek > stop ? stop * 2 : at
      map.set(
        node.scenario.id,
        readout.map((id, i) => ({
          id,
          delta: simulate(node.scenario, id, baselines).points[idx].value - ctrl[i],
        })),
      )
    }
    return map
  }, [tree, control, baselines, readout, cursorWeek, status])

  return (
    <section className="bmap" data-hint={t.ws.hints.map}>
      <header className="pane__head">
        <h3 className="pane__title">{t.ws.mapTitle}</h3>
        <div className="bmap__legend">
          <span className="bmap__key">
            <svg viewBox="0 0 22 6" aria-hidden="true">
              <line x1="0" y1="3" x2="22" y2="3" strokeWidth="1.6" stroke="currentColor" />
            </svg>
            {t.ws.legendActive}
          </span>
          <span className="bmap__key bmap__key--stop">
            <svg viewBox="0 0 22 6" aria-hidden="true">
              <line
                x1="0"
                y1="3"
                x2="22"
                y2="3"
                strokeWidth="1.6"
                strokeDasharray="4 3"
                stroke="currentColor"
              />
            </svg>
            {t.ws.legendStopped}
          </span>
        </div>
        <div className="bmap__counts">
          <span className="bmap__count" data-kind="active">
            {fmt(t.ws.mapActive, { n: activeCount.toLocaleString('en-US') })}
          </span>
          <span className="bmap__count" data-kind="stopped">
            {fmt(t.ws.mapStopped, { n: stoppedCount.toLocaleString('en-US') })}
          </span>
        </div>
      </header>

      <div className="bmap__scroll figure-ltr" dir="ltr" ref={scrollRef}>
        <svg
          className="bmap__svg"
          viewBox={`0 0 ${width} ${height}`}
          style={{ height: `${height}px`, width: `${width}px` }}
          role="img"
          aria-label={t.ws.mapTitle}
        >
          {/* -------------------------------------------------- week axis */}
          {[0, 8, 16, 24, 32, HORIZON_WEEKS].map((w) => (
            <g key={w}>
              <line className="bmap-grid" x1={x(w)} y1={PAD_T - 12} x2={x(w)} y2={height - PAD_B} />
              <text className="bmap-tick" x={x(w)} y={PAD_T - 18} textAnchor="middle">
                {w}
              </text>
            </g>
          ))}
          <text className="bmap-axis" x={4} y={PAD_T - 18}>
            {t.ws.week}
          </text>

          {tree.flat.map((node) => (
            <Branch
              key={node.scenario.id}
              node={node}
              x={x}
              y={y}
              parentRow={node.parent ? y(rowOf.get(node.parent.id) ?? node.row) : y(node.row)}
              status={status.get(node.scenario.id)}
              readouts={readouts.get(node.scenario.id)}
              selected={node.scenario.id === selectedId}
              cursorWeek={cursorWeek}
              label={label}
              eventText={eventText}
              onSelect={onSelect}
            />
          ))}

          {/* the shared playhead, drawn last so it sits over every branch */}
          <line
            className="bmap-cursor"
            x1={x(cursorWeek)}
            y1={PAD_T - 12}
            x2={x(cursorWeek)}
            y2={height - PAD_B}
          />
          <g transform={`translate(${x(cursorWeek)} ${PAD_T - 12})`}>
            <rect className="bmap-cursor-chip" x={-19} y={-15} width={38} height={15} rx={2} />
            <text className="bmap-cursor-text" x={0} y={-4} textAnchor="middle">
              {Math.round(cursorWeek * 2) / 2}
            </text>
          </g>
        </svg>
      </div>
    </section>
  )
}

function Branch({
  node,
  x,
  y,
  parentRow,
  status,
  readouts,
  selected,
  cursorWeek,
  label,
  eventText,
  onSelect,
}: {
  node: BranchNode
  x: (w: number) => number
  y: (row: number) => number
  parentRow: number
  status?: BranchStatus
  readouts?: { id: IndicatorId; delta: number }[]
  selected: boolean
  cursorWeek: number
  label: (s: Scenario) => string
  eventText: (e: ProtocolEvent) => string
  onSelect: (id: string) => void
}) {
  const { t } = useI18n()
  const s = node.scenario
  const control = isControl(s)
  const color = control ? 'var(--arm-control)' : armColor(s)
  const row = y(node.row)
  const start = x(s.branchWeek)
  const stop = status?.stopWeek ?? -1
  const end = x(stop >= 0 ? stop : HORIZON_WEEKS)
  const readoutX = x(HORIZON_WEEKS) + 16

  const events = divergence(s, node.parent)

  return (
    <g
      className="bmap-branch"
      data-selected={selected}
      data-stopped={stop >= 0}
      data-control={control}
      style={{ ['--bc' as string]: color }}
      onClick={() => onSelect(s.id)}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect(s.id)
        }
      }}
    >
      {/* the elbow back to the parent: this is the branch point, and it is the
          one thing the previous interface had no way of showing */}
      {node.parent && (
        <path
          className="bmap-elbow"
          d={`M${start} ${parentRow}L${start} ${row - 12}Q${start} ${row} ${start + 12} ${row}`}
        />
      )}

      <line className="bmap-line" x1={start} y1={row} x2={end} y2={row} />

      {/* where the branch stops being viable */}
      {stop >= 0 && (
        <>
          <line className="bmap-line bmap-line--dead" x1={end} y1={row} x2={x(HORIZON_WEEKS)} y2={row} />
          <g transform={`translate(${end} ${row})`}>
            <circle className="bmap-stop" r={5} />
            <path className="bmap-stop-x" d="M-2.4 -2.4L2.4 2.4M2.4 -2.4L-2.4 2.4" />
          </g>
          <text className="bmap-stop-label" x={end + 12} y={row - 9}>
            {t.ws.stopped}
            {status?.stopReason ? ` · ${indicatorName(t, INDICATOR_BY_ID[status.stopReason])}` : ''}
          </text>
        </>
      )}

      <circle className="bmap-node" cx={start} cy={row} r={selected ? 5 : 3.6} />

      <text className="bmap-name" x={start + 12} y={row - 8}>
        {label(s)}
      </text>

      {control ? (
        <text className="bmap-sub" x={start + 12} y={row + 12}>
          {t.ws.controlNote}
        </text>
      ) : (
        events.length > 0 && (
          <text className="bmap-sub" x={start + 12} y={row + 12}>
            {events.map(eventText).join(' · ')}
          </text>
        )
      )}

      {/* the readout at the playhead, so the map answers "how far apart are
          these right now" without leaving it */}
      {readouts && cursorWeek > s.branchWeek && (
        <g transform={`translate(${readoutX} ${row - 17})`} className="bmap-readout">
          {readouts.map((r, i) => (
            <g key={r.id} transform={`translate(0 ${i * 12})`}>
              <text className="bmap-readout-name" x={0} y={0}>
                {indicatorName(t, INDICATOR_BY_ID[r.id])}
              </text>
              <text className="bmap-readout-value" x={92} y={0} textAnchor="end" data-dir={r.delta >= 0 ? 'up' : 'down'}>
                {r.delta >= 0 ? '+' : ''}
                {formatValue(r.id, r.delta)}
              </text>
            </g>
          ))}
        </g>
      )}

      {selected && (
        <text className="bmap-selected" x={end - 6} y={row + 14} textAnchor="end">
          {t.ws.selected}
        </text>
      )}
    </g>
  )
}
