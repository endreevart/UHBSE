import type { Vec } from './curve'
import { HORIZON_WEEKS } from '../engine/model'
import { PIPELINE_MAX_WEEKS } from './pipelineTree'
import {
  MIN_VISIBLE_WEEKS,
  maxZoomOutSpanWeeks,
  viewportSpanWeeks,
  visibleTimelineSpanWeeks,
} from './timeRuler'
import {
  TREE_AXIS_Y,
  TREE_BRANCH_X,
  TREE_CONTENT_BOTTOM,
  TREE_CONTENT_TOP,
  TREE_END_X,
  TREE_PLOT_TOP,
  TREE_TRUNK_X0,
  type TreeBranch,
  treeWeekX,
} from './trajectoryTree'

export const FAN_SPREAD_MIN = 1
export const FAN_SPREAD_MAX = 4
export const FAN_SPREAD_STEP = 1.18

export const FAN_ZOOM_STEP = 1.12

/** Left edge of the instrument — baseline stays here when scrollX = 0. */
export const LEFT_ANCHOR = TREE_TRUNK_X0 - 20
/** Virtual timeline end in world coordinates (≈ 240 weeks). */
export const TIMELINE_END_X = treeWeekX(PIPELINE_MAX_WEEKS) + 80

const TRUNK_LEADING_PX = TREE_BRANCH_X - LEFT_ANCHOR
const CONTENT_TAIL_PAD = 56

export interface FanView {
  spread: number
  scrollX: number
  cy: number
  zoom: number
}

export interface FanViewContext {
  aspect: number
  simulationEndWeek: number
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

export function clampFanSpread(spread: number) {
  return clamp(spread, FAN_SPREAD_MIN, FAN_SPREAD_MAX)
}

export const ENSEMBLE_VIEW_W = TREE_END_X - TREE_TRUNK_X0 + 70

export function fanFrameSize(spread: number) {
  const baseSpan = TREE_CONTENT_BOTTOM - TREE_CONTENT_TOP
  const extraY = ((spread - 1) * baseSpan) / 2
  const h = TREE_CONTENT_BOTTOM - TREE_PLOT_TOP + 56 + extraY * 2
  const w = ENSEMBLE_VIEW_W
  return { w, h, baseSpan }
}

function visibleSize(spread: number, zoom: number, aspect: number) {
  const frame = fanFrameSize(spread)
  let vw = frame.w / zoom
  let vh = frame.h / zoom
  if (vw / vh > aspect) {
    vh = vw / aspect
  } else {
    vw = vh * aspect
  }
  return { vw, vh, frame }
}

/** Drawable width from baseline root through simulation horizon. */
export function fanContentWidth(simulationEndWeek: number) {
  return treeWeekX(simulationEndWeek) + CONTENT_TAIL_PAD - LEFT_ANCHOR
}

/** Horizontal scroll limits; allows negative scroll to center when viewport is wider than content. */
export function scrollBounds(vw: number, simulationEndWeek: number) {
  const contentW = fanContentWidth(simulationEndWeek)
  const minScrollX = vw > contentW ? -(vw - contentW) / 2 : 0
  const maxScrollX = Math.max(minScrollX, TIMELINE_END_X - LEFT_ANCHOR - vw)
  return { minScrollX, maxScrollX }
}

export function centeredScrollX(vw: number, simulationEndWeek: number) {
  return scrollBounds(vw, simulationEndWeek).minScrollX
}

function verticalCenterY(
  vh: number,
  spread: number,
  frame: ReturnType<typeof fanFrameSize>,
) {
  const plotCy = (TREE_PLOT_TOP + TREE_AXIS_Y) / 2
  const extraY = ((spread - 1) * frame.baseSpan) / 2
  const pad = 20
  const plotH = TREE_AXIS_Y - TREE_PLOT_TOP + 48
  if (vh >= plotH) return plotCy
  const minCy = TREE_CONTENT_TOP - pad + vh / 2 - extraY * 0.2
  const maxCy = TREE_CONTENT_BOTTOM + pad - vh / 2 + extraY * 0.2
  return clamp(plotCy, minCy, maxCy)
}

/** Zoom at which the visible timeline span equals `spanWeeks` (scrollX = 0). */
export function zoomForTimelineSpan(spanWeeks: number, spread: number, aspect: number): number {
  const target = Math.max(MIN_VISIBLE_WEEKS / 4, spanWeeks)
  let lo = 0.05
  let hi = 300_000
  for (let i = 0; i < 56; i += 1) {
    const mid = (lo + hi) / 2
    const { vw } = visibleSize(spread, mid, aspect)
    const span = viewportSpanWeeks(vw)
    if (span > target) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}

/** Most zoomed-out: show the full simulation horizon. */
export function minFanZoom(spread: number, aspect: number, simulationEndWeek: number) {
  const span = maxZoomOutSpanWeeks(simulationEndWeek)
  return zoomForTimelineSpan(span, spread, aspect)
}

/** Most zoomed-in: ~1 hour on the timeline. */
export function maxFanZoom(spread: number, aspect: number) {
  return zoomForTimelineSpan(MIN_VISIBLE_WEEKS, spread, aspect)
}

/** Preset spans for trading-chart style zoom levels. */
export const ZOOM_PRESET_DAY_WEEKS = 1 / 7
export const ZOOM_PRESET_WEEK_WEEKS = 1
export const ZOOM_PRESET_MONTH_WEEKS = 4
export const ZOOM_PRESET_YEAR_WEEKS = 52

/** Zoom to a fixed timeline window centered on `centerWeek`. */
export function zoomToTimelineSpan(
  view: FanView,
  ctx: FanViewContext,
  spanWeeks: number,
  centerWeek: number,
): FanView {
  const zoom = zoomForTimelineSpan(spanWeeks, view.spread, ctx.aspect)
  const { vw, vh, frame } = visibleSize(view.spread, zoom, ctx.aspect)
  const centerX = treeWeekX(centerWeek)
  const scrollX = centerX - LEFT_ANCHOR - vw / 2
  return constrainFanView(
    {
      ...view,
      zoom,
      scrollX,
      cy: verticalCenterY(vh, view.spread, frame),
    },
    ctx,
  )
}

export function clampFanZoom(
  zoom: number,
  spread: number,
  aspect: number,
  simulationEndWeek: number,
) {
  return clamp(zoom, minFanZoom(spread, aspect, simulationEndWeek), maxFanZoom(spread, aspect))
}

export function defaultFanView(simulationEndWeek = HORIZON_WEEKS, ctx?: FanViewContext): FanView {
  const fanCtx = ctx ?? { aspect: 16 / 9, simulationEndWeek }
  return resetFanView(fanCtx)
}

/** Full-period, centered view — used on reset and «Весь период». */
export function resetFanView(ctx: FanViewContext): FanView {
  return fitFullTimelineView(
    {
      spread: FAN_SPREAD_MIN,
      scrollX: 0,
      cy: (TREE_CONTENT_TOP + TREE_CONTENT_BOTTOM) / 2,
      zoom: 1,
    },
    ctx,
  )
}

/** Zoom out and center — show the whole elapsed simulation window. */
export function fitFullTimelineView(view: FanView, ctx: FanViewContext): FanView {
  const span = maxZoomOutSpanWeeks(ctx.simulationEndWeek)
  const zoom = zoomForTimelineSpan(span, view.spread, ctx.aspect)
  const { vw, vh, frame } = visibleSize(view.spread, zoom, ctx.aspect)
  return constrainFanView(
    {
      ...view,
      scrollX: centeredScrollX(vw, ctx.simulationEndWeek),
      zoom,
      cy: verticalCenterY(vh, view.spread, frame),
    },
    ctx,
  )
}

export function isFullTimelineVisible(view: FanView, ctx: FanViewContext): boolean {
  const fitted = fitFullTimelineView(view, ctx)
  return (
    Math.abs(view.zoom - fitted.zoom) / Math.max(fitted.zoom, 0.001) < 0.04 &&
    Math.abs(view.scrollX - fitted.scrollX) < 2
  )
}

export function constrainFanView(view: FanView, ctx: FanViewContext): FanView {
  const { aspect, simulationEndWeek } = ctx
  const spread = clampFanSpread(view.spread)
  const zoom = clampFanZoom(view.zoom, spread, aspect, simulationEndWeek)
  const { vw, vh, frame } = visibleSize(spread, zoom, aspect)

  const { minScrollX, maxScrollX } = scrollBounds(vw, simulationEndWeek)
  const scrollX = clamp(view.scrollX, minScrollX, maxScrollX)

  const extraY = ((spread - 1) * frame.baseSpan) / 2
  const pad = 20
  const plotH = TREE_AXIS_Y - TREE_PLOT_TOP + 48
  let cy: number
  if (vh >= plotH) {
    cy = verticalCenterY(vh, spread, frame)
  } else {
    const minCy = TREE_CONTENT_TOP - pad + vh / 2 - extraY * 0.2
    const maxCy = TREE_CONTENT_BOTTOM + pad - vh / 2 + extraY * 0.2
    cy = clamp(view.cy, minCy, maxCy)
  }

  return { spread, scrollX, cy, zoom }
}

export function fanCameraRect(view: FanView, ctx: FanViewContext) {
  const v = constrainFanView(view, ctx)
  const { vw, vh } = visibleSize(v.spread, v.zoom, ctx.aspect)
  return {
    x: LEFT_ANCHOR + v.scrollX,
    y: v.cy - vh / 2,
    w: vw,
    h: vh,
  }
}

export function fanSpreadPercent(spread: number) {
  return Math.round(spread * 100)
}

export function visibleSpanLabel(ctx: FanViewContext, view: FanView): number {
  const box = fanCameraRect(view, ctx)
  return visibleTimelineSpanWeeks(box)
}

/** Zoom toward a screen point; keeps the anchor under the cursor. */
export function zoomViewAt(
  view: FanView,
  ctx: FanViewContext,
  worldX: number,
  worldY: number,
  screenFx: number,
  screenFy: number,
  newZoom: number,
): FanView {
  const zoom = clampFanZoom(newZoom, view.spread, ctx.aspect, ctx.simulationEndWeek)
  const { vw, vh } = visibleSize(view.spread, zoom, ctx.aspect)
  const scrollX = worldX - LEFT_ANCHOR - screenFx * vw
  const cy = worldY - vh * (screenFy - 0.5)
  return constrainFanView({ ...view, zoom, scrollX, cy }, ctx)
}

export function focusFanOnBranch(
  branches: TreeBranch[],
  branchIndex: number,
  view: FanView,
  ctx: FanViewContext,
): FanView {
  const br = branches.find((b) => b.index === branchIndex)
  if (!br) return view

  const endWeek = br.stop >= 0 ? br.stop : HORIZON_WEEKS
  const endX = treeWeekX(endWeek)
  const { vw } = visibleSize(view.spread, view.zoom, ctx.aspect)
  const scrollX = endX - vw * 0.62 + TRUNK_LEADING_PX * 0.35

  return constrainFanView(
    {
      spread: clampFanSpread(Math.max(view.spread, 2.2)),
      scrollX,
      cy: br.endY,
      zoom: clampFanZoom(Math.max(view.zoom, 1.8), view.spread, ctx.aspect, ctx.simulationEndWeek),
    },
    ctx,
  )
}

export function worldUiScale(zoom: number): number {
  return 1 / Math.max(1, zoom)
}

export function fixedLabelTransform(zoom: number, x: number, y: number): string | undefined {
  const s = worldUiScale(zoom)
  if (s >= 0.999) return undefined
  return `translate(${x} ${y}) scale(${s}) translate(${-x} ${-y})`
}

export function isInViewX(x: number, box: { x: number; w: number }, pad = 0): boolean {
  return x >= box.x - pad && x <= box.x + box.w + pad
}

export function clientToSvg(svg: SVGSVGElement, clientX: number, clientY: number) {
  const pt = svg.createSVGPoint()
  pt.x = clientX
  pt.y = clientY
  const ctm = svg.getScreenCTM()
  if (!ctm) return { x: 0, y: 0 }
  const p = pt.matrixTransform(ctm.inverse())
  return { x: p.x, y: p.y }
}

export function branchYAt(pts: Vec[], x: number): number | null {
  if (pts.length < 2 || x < pts[0].x || x > pts[pts.length - 1].x) return null
  for (let i = 0; i < pts.length - 1; i += 1) {
    const a = pts[i]
    const b = pts[i + 1]
    if (x >= a.x && x <= b.x) {
      const t = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x)
      return a.y + (b.y - a.y) * t
    }
  }
  return null
}

export function pickBranchAtPoint(
  branches: TreeBranch[],
  x: number,
  y: number,
  spread: number,
): number | null {
  if (x < TREE_BRANCH_X - 8) return null

  let best = -1
  let bestDist = Infinity
  const threshold = 10 + spread * 6

  for (const br of branches) {
    const yCurve = branchYAt(br.midPts, x)
    if (yCurve === null) continue
    const dist = Math.abs(yCurve - y)
    if (dist < bestDist) {
      bestDist = dist
      best = br.index
    }
  }

  return best >= 0 && bestDist < threshold ? best : null
}

export const ENSEMBLE_HIT = {
  x: LEFT_ANCHOR,
  y: TREE_CONTENT_TOP,
  w: ENSEMBLE_VIEW_W,
  h: TREE_CONTENT_BOTTOM - TREE_CONTENT_TOP,
} as const
