import { useCallback, useRef } from 'react'
import type { ProtocolEvent } from '../engine/graph'
import { useI18n } from '../i18n'

const VW = 1000
const PAD = 10
const TRACK_H = 74
const AXIS_Y = 58
const OVER_H = 26

/** Smallest window the magnifier will close to, in weeks. */
const MIN_SPAN = 4

const GLYPH: Record<ProtocolEvent['kind'], string> = {
  added: '+',
  removed: '×',
  raised: '↑',
  lowered: '↓',
}

interface Props {
  horizon: number
  cursorWeek: number
  events: ProtocolEvent[]
  eventText: (e: ProtocolEvent) => string
  view: [number, number]
  armColor: string
  onView: (v: [number, number]) => void
  onScrub: (week: number) => void
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

/**
 * One timeline for the whole workspace, at two scales at once.
 *
 * A thirty-six week horizon holding a dozen protocol changes cannot be scrubbed
 * accurately with a plain slider: the week you want is half a pixel wide. The
 * lower strip keeps the whole run in view and carries a window; the upper track
 * shows only that window, so precision is bought without ever losing the place.
 *
 * Protocol changes hang off the axis rather than living in a list beside it. A
 * dose change is an event in time, and the timeline is where time is.
 */
export function Timeline({
  horizon,
  cursorWeek,
  events,
  eventText,
  view,
  armColor,
  onView,
  onScrub,
}: Props) {
  const { t } = useI18n()
  const detail = useRef<SVGSVGElement>(null)
  const overview = useRef<SVGSVGElement>(null)
  const drag = useRef<'window' | 'start' | 'end' | null>(null)
  const grab = useRef(0)

  const [v0, v1] = view
  const span = Math.max(MIN_SPAN, v1 - v0)

  const toX = (w: number) => PAD + ((w - v0) / span) * (VW - PAD * 2)
  const overX = (w: number) => PAD + (w / horizon) * (VW - PAD * 2)

  /** Pointer position as a week, in whichever track it lands. */
  const weekAt = useCallback(
    (svg: SVGSVGElement | null, clientX: number, full: boolean) => {
      if (!svg) return 0
      const box = svg.getBoundingClientRect()
      const ratio = (clientX - box.left) / box.width
      const units = ratio * VW
      const t01 = (units - PAD) / (VW - PAD * 2)
      return full ? clamp(t01 * horizon, 0, horizon) : clamp(v0 + t01 * span, 0, horizon)
    },
    [horizon, v0, span],
  )

  const zoom = useCallback(
    (factor: number) => {
      const next = clamp(span * factor, MIN_SPAN, horizon)
      const centre = cursorWeek >= v0 && cursorWeek <= v1 ? cursorWeek : v0 + span / 2
      const start = clamp(centre - next / 2, 0, horizon - next)
      onView([start, start + next])
    },
    [span, horizon, cursorWeek, v0, v1, onView],
  )

  /* ------------------------------------------------------- brush drags */

  const onOverviewDown = (e: React.PointerEvent<SVGSVGElement>) => {
    const target = (e.target as Element).getAttribute('data-grip')
    const week = weekAt(overview.current, e.clientX, true)
    e.currentTarget.setPointerCapture(e.pointerId)
    if (target === 'start' || target === 'end') {
      drag.current = target
      return
    }
    if (week >= v0 && week <= v1) {
      drag.current = 'window'
      grab.current = week - v0
      return
    }
    // a click outside the window recentres it there rather than doing nothing
    const start = clamp(week - span / 2, 0, horizon - span)
    onView([start, start + span])
    drag.current = 'window'
    grab.current = week - start
  }

  const onOverviewMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag.current) return
    const week = weekAt(overview.current, e.clientX, true)
    if (drag.current === 'window') {
      const start = clamp(week - grab.current, 0, horizon - span)
      onView([start, start + span])
      return
    }
    if (drag.current === 'start') {
      onView([clamp(week, 0, v1 - MIN_SPAN), v1])
      return
    }
    onView([v0, clamp(week, v0 + MIN_SPAN, horizon)])
  }

  const endDrag = (e: React.PointerEvent<SVGSVGElement>) => {
    drag.current = null
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  /* --------------------------------------------------------- detail track */

  const scrubbing = useRef(false)

  const onDetailDown = (e: React.PointerEvent<SVGSVGElement>) => {
    scrubbing.current = true
    e.currentTarget.setPointerCapture(e.pointerId)
    onScrub(weekAt(detail.current, e.clientX, false))
  }

  const onDetailMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!scrubbing.current) return
    onScrub(weekAt(detail.current, e.clientX, false))
  }

  const onDetailUp = (e: React.PointerEvent<SVGSVGElement>) => {
    scrubbing.current = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  /* the tick pitch follows the zoom, so the axis never turns into a comb */
  const pitch = span > 24 ? 6 : span > 12 ? 4 : span > 6 ? 2 : 1
  const ticks: number[] = []
  for (let w = Math.ceil(v0 / pitch) * pitch; w <= v1; w += pitch) ticks.push(w)

  const visible = events.filter((e) => e.week >= v0 - 0.01 && e.week <= v1 + 0.01)

  return (
    <div className="tl" data-hint={t.ws.hints.timeline}>
      <div className="tl__detail figure-ltr" dir="ltr">
        <svg
          ref={detail}
          viewBox={`0 0 ${VW} ${TRACK_H}`}
          className="tl__svg"
          onPointerDown={onDetailDown}
          onPointerMove={onDetailMove}
          onPointerUp={onDetailUp}
          onPointerCancel={onDetailUp}
          role="slider"
          tabIndex={0}
          aria-label={t.hero.figure.time}
          aria-valuemin={0}
          aria-valuemax={horizon}
          aria-valuenow={Math.round(cursorWeek * 2) / 2}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') onScrub(cursorWeek - 0.5)
            if (e.key === 'ArrowRight') onScrub(cursorWeek + 0.5)
          }}
        >
          <line className="tl__axis" x1={PAD} y1={AXIS_Y} x2={VW - PAD} y2={AXIS_Y} />

          {ticks.map((w) => (
            <g key={w}>
              <line className="tl__tick" x1={toX(w)} y1={AXIS_Y} x2={toX(w)} y2={AXIS_Y + 6} />
              <text className="tl__tick-label" x={toX(w)} y={AXIS_Y + 17} textAnchor="middle">
                {w}
              </text>
            </g>
          ))}

          {visible.map((e, i) => {
            const x = toX(e.week)
            // two heights alternating: a cluster of changes in the same fortnight
            // would otherwise stack its labels on top of each other
            const y = i % 2 === 0 ? 16 : 34
            return (
              <g
                key={`${e.spec}-${e.week}-${e.kind}`}
                className="tl__event"
                data-kind={e.kind}
                onPointerDown={(ev) => {
                  ev.stopPropagation()
                  onScrub(e.week)
                }}
              >
                <title>{eventText(e)}</title>
                <line className="tl__stalk" x1={x} y1={y + 7} x2={x} y2={AXIS_Y} />
                <circle className="tl__event-dot" cx={x} cy={y} r={7} style={{ ['--sc' as string]: armColor }} />
                <text className="tl__event-glyph" x={x} y={y + 3.5} textAnchor="middle">
                  {GLYPH[e.kind]}
                </text>
              </g>
            )
          })}

          <g className="tl__head" style={{ ['--sc' as string]: armColor }}>
            <line className="tl__head-line" x1={toX(cursorWeek)} y1={6} x2={toX(cursorWeek)} y2={AXIS_Y} />
            <path
              className="tl__head-grip"
              d={`M${toX(cursorWeek) - 5} 0h10v7l-5 5l-5-5z`}
            />
          </g>
        </svg>
      </div>

      <div className="tl__over figure-ltr" dir="ltr">
        <svg
          ref={overview}
          viewBox={`0 0 ${VW} ${OVER_H}`}
          className="tl__svg tl__svg--over"
          onPointerDown={onOverviewDown}
          onPointerMove={onOverviewMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          role="presentation"
        >
          <rect className="tl__over-bg" x={PAD} y={4} width={VW - PAD * 2} height={OVER_H - 8} rx={2} />

          {events.map((e) => (
            <line
              key={`o-${e.spec}-${e.week}-${e.kind}`}
              className="tl__over-tick"
              x1={overX(e.week)}
              y1={6}
              x2={overX(e.week)}
              y2={OVER_H - 6}
            />
          ))}

          <line
            className="tl__over-head"
            x1={overX(cursorWeek)}
            y1={3}
            x2={overX(cursorWeek)}
            y2={OVER_H - 3}
            style={{ ['--sc' as string]: armColor }}
          />

          <rect
            className="tl__brush"
            data-grip="window"
            x={overX(v0)}
            y={3}
            width={Math.max(4, overX(v1) - overX(v0))}
            height={OVER_H - 6}
            rx={2}
          />
          <rect className="tl__grip" data-grip="start" x={overX(v0) - 3} y={3} width={6} height={OVER_H - 6} />
          <rect className="tl__grip" data-grip="end" x={overX(v1) - 3} y={3} width={6} height={OVER_H - 6} />
        </svg>

        <div className="tl__zoom">
          <button type="button" className="ws__key" onClick={() => zoom(0.5)} aria-label={t.ws.zoomIn}>
            <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1 5h10v2H1zM5 1h2v10H5z" /></svg>
          </button>
          <button type="button" className="ws__key" onClick={() => zoom(2)} aria-label={t.ws.zoomOut}>
            <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1 5h10v2H1z" /></svg>
          </button>
          <span className="tl__span tabular">
            {Math.round(v0)}–{Math.round(v1)}
          </span>
        </div>
      </div>
    </div>
  )
}
