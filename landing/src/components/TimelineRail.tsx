import { useCallback, useRef } from 'react'
import { HORIZON_WEEKS } from '../engine/model'
import {
  buildTimeTicks,
  formatVisibleSpan,
  treeXAtWeek,
  weekAtTreeX,
  worldXToRailPercent,
} from '../lib/timeRuler'

interface Props {
  box: { x: number; w: number }
  cursorWeek: number
  horizonWeeks?: number
  locale: string
  timeLabel: string
  scrubLabel: string
  onScrub: (week: number) => void
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

function snapWeek(week: number, spanWeeks: number) {
  const step =
    spanWeeks <= 1 / 7
      ? 1 / 7
      : spanWeeks <= 0.5
        ? 1 / 14
        : spanWeeks <= 2
          ? 0.5
          : spanWeeks <= 8
            ? 1
            : 2
  return Math.round(clamp(week, 0, HORIZON_WEEKS) / step) * step
}

export function TimelineRail({
  box,
  cursorWeek,
  horizonWeeks = HORIZON_WEEKS,
  locale,
  timeLabel,
  scrubLabel,
  onScrub,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const week0 = weekAtTreeX(box.x)
  const week1 = weekAtTreeX(box.x + box.w)
  const spanWeeks = Math.max(week1 - week0, 0.001)

  const ticks = buildTimeTicks(week0, week1, locale, horizonWeeks)

  const weekAtClientX = useCallback(
    (clientX: number) => {
      const track = trackRef.current
      if (!track) return cursorWeek
      const rect = track.getBoundingClientRect()
      const ratio = clamp((clientX - rect.left) / rect.width, 0, 1)
      const worldX = box.x + ratio * box.w
      return snapWeek(weekAtTreeX(worldX), spanWeeks)
    },
    [box.x, box.w, cursorWeek, spanWeeks],
  )

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true
    e.currentTarget.setPointerCapture(e.pointerId)
    onScrub(weekAtClientX(e.clientX))
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    onScrub(weekAtClientX(e.clientX))
  }

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false
    e.currentTarget.releasePointerCapture(e.pointerId)
  }

  const cursorPct = worldXToRailPercent(treeXAtWeek(cursorWeek), box)
  const showCursor = cursorPct >= -2 && cursorPct <= 102

  return (
    <div className="ensemble-tree__time-rail" aria-hidden="false">
      <div className="ensemble-tree__time-rail-head">
        <span className="ensemble-tree__time-rail-title mono-label">{timeLabel}</span>
        <span className="ensemble-tree__time-rail-span tabular">{formatVisibleSpan(spanWeeks, locale)}</span>
      </div>

      <div
        ref={trackRef}
        className="ensemble-tree__time-rail-track ensemble-tree__time-rail-track--scrub"
        role="slider"
        aria-label={scrubLabel}
        aria-valuemin={0}
        aria-valuemax={horizonWeeks}
        aria-valuenow={cursorWeek}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {ticks.map((tick) => {
          const pct = worldXToRailPercent(treeXAtWeek(tick.week), box)
          if (pct < -4 || pct > 104) return null
          return (
            <div
              key={`${tick.week}-${tick.label}`}
              className={`ensemble-tree__time-tick${tick.major ? ' ensemble-tree__time-tick--major' : ''}`}
              style={{ left: `${pct}%` }}
            >
              <span className="ensemble-tree__time-tick-mark" />
              <span className="ensemble-tree__time-tick-label tabular">{tick.label}</span>
            </div>
          )
        })}

        {showCursor && (
          <div className="ensemble-tree__time-cursor" style={{ left: `${cursorPct}%` }}>
            <span className="ensemble-tree__time-cursor-line" />
            <span className="ensemble-tree__time-cursor-thumb" />
          </div>
        )}
      </div>
    </div>
  )
}
