import { TREE_BRANCH_X, TREE_PX_PER_WEEK, treeWeekX } from './trajectoryTree'

/** Finest visible window when fully zoomed in (1 hour — trading-chart style). */
export const MIN_VISIBLE_HOURS = 1
const HOURS_PER_WEEK = 168
export const MIN_VISIBLE_WEEKS = MIN_VISIBLE_HOURS / HOURS_PER_WEEK
/** Coarsest window when fully zoomed out — full simulation horizon. */
export const MAX_VISIBLE_WEEKS = 560

export function weekAtTreeX(px: number): number {
  return (px - TREE_BRANCH_X) / TREE_PX_PER_WEEK
}

export function treeXAtWeek(week: number): number {
  return treeWeekX(week)
}

/** Width of the viewport in simulation weeks (independent of scroll position). */
export function viewportSpanWeeks(viewportWidthPx: number): number {
  return viewportWidthPx / TREE_PX_PER_WEEK
}

/** How many weeks of timeline are visible in the camera box. */
export function visibleTimelineSpanWeeks(box: { x: number; w: number }): number {
  return Math.max(MIN_VISIBLE_WEEKS / 4, viewportSpanWeeks(box.w))
}

/** Tick step in weeks for a visible span (exported for grid rendering). */
export function tickStepForSpan(spanWeeks: number): number {
  return niceStep(spanWeeks)
}

/** Max zoom-out window: full elapsed simulation. */
export function maxZoomOutSpanWeeks(simulationEndWeek: number): number {
  return Math.max(MIN_VISIBLE_WEEKS, simulationEndWeek)
}

export interface TimeTick {
  week: number
  major: boolean
  label: string
}

function niceStep(spanWeeks: number): number {
  const candidates = [
    1 / HOURS_PER_WEEK, // 1 h
    2 / HOURS_PER_WEEK,
    6 / HOURS_PER_WEEK,
    12 / HOURS_PER_WEEK,
    1 / 7, // 1 day
    2 / 7,
    1,
    2,
    4,
    8,
    12,
    26,
    52,
  ]
  const target = spanWeeks / 8
  let best = candidates[0]
  for (const c of candidates) {
    if (c >= target * 0.6) {
      best = c
      break
    }
    best = c
  }
  return best
}

function suffix(locale: string, kind: 'm' | 'h' | 'd' | 'w' | 'y'): string {
  if (locale.startsWith('ru')) {
    return { m: 'м', h: 'ч', d: 'д', w: 'нед', y: 'г' }[kind]
  }
  return { m: 'm', h: 'h', d: 'd', w: 'w', y: 'y' }[kind]
}

function formatWeekLabel(week: number, locale: string, spanWeeks = 52): string {
  const abs = Math.abs(week)
  const hours = abs * HOURS_PER_WEEK

  if (spanWeeks <= 1 / 7 && week > 0) {
    const h = Math.round(hours * 10) / 10
    return new Intl.NumberFormat(locale, { maximumFractionDigits: h < 10 ? 1 : 0 }).format(h) + suffix(locale, 'h')
  }
  if (spanWeeks <= 2 && week > 0) {
    const days = Math.round(week * 7)
    const dayLabel = locale.startsWith('ru') ? 'д' : 'd'
    return `${days}${dayLabel}`
  }

  if (hours < 1) {
    const mins = Math.round(hours * 60)
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(mins) + suffix(locale, 'm')
  }
  if (hours < 24) {
    const h = hours < 10 ? Math.round(hours * 10) / 10 : Math.round(hours)
    return new Intl.NumberFormat(locale, { maximumFractionDigits: hours < 10 ? 1 : 0 }).format(h) + suffix(locale, 'h')
  }
  if (abs < 2) {
    const days = Math.round(abs * 7 * 10) / 10
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(days) + suffix(locale, 'd')
  }
  if (abs < 8) {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(abs) + suffix(locale, 'w')
  }
  if (abs < 52) {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(Math.round(abs)) + suffix(locale, 'w')
  }
  const years = abs / 52
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(years) + suffix(locale, 'y')
}

/** Ticks for the fixed top ruler inside a visible week range. */
export function buildTimeTicks(
  week0: number,
  week1: number,
  locale: string,
  simulationEndWeek: number,
): TimeTick[] {
  const span = Math.max(week1 - week0, MIN_VISIBLE_WEEKS / 4)
  const step = niceStep(span)
  const majorEvery = step >= 1 ? step : step * 4

  const start = Math.floor(week0 / step) * step
  const end = week1 + step
  const ticks: TimeTick[] = []

  for (let w = start; w <= end; w += step) {
    if (w < -step * 0.01 || w > simulationEndWeek + span * 0.05) continue
    const major = Math.abs(w % majorEvery) < step * 0.01 || w === 0
    ticks.push({
      week: w,
      major,
      label: w === 0 ? '0' : formatWeekLabel(w, locale, span),
    })
  }
  return ticks
}

/** Human-readable span for the zoom readout. */
export function formatVisibleSpan(spanWeeks: number, locale: string): string {
  return formatWeekLabel(spanWeeks, locale, spanWeeks)
}

/** Map world X to 0..1 position across the viewport box. */
export function worldXToRailPercent(worldX: number, box: { x: number; w: number }): number {
  return ((worldX - box.x) / box.w) * 100
}
