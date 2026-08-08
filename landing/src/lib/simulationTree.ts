import { FACTORS, branchPanelIndex, branchPanelValue, WEEKS, type RunResult } from '../engine/cohort'
import { HORIZON_WEEKS, INDICATOR_BY_ID, type IndicatorId } from '../engine/model'
import type { Baselines, Subject } from '../engine/subject'
import { cohortMedianPanelBurden, panelBurdenAt } from './branchComposite'
import type { Vec } from './curve'
import { sampleBranch } from './curve'
import { PIPELINE_MAX_WEEKS } from './pipelineTree'
import {
  TREE_BASE_Y,
  TREE_BRANCH_X,
  TREE_CONTENT_BOTTOM,
  TREE_CONTENT_TOP,
  TREE_TRUNK_X0,
  branchOutcome,
  branchPathOutcome,
  clampPlotY,
  treeWeekX,
  valueToYFromBaseline,
  type TreeBranch,
} from './trajectoryTree'

/** Observed baseline — the single root all simulations grow from. */
export const TREE_ROOT_X = TREE_TRUNK_X0 + 8

export const COMPOSITE_BURDEN_SIGMA = 0.35

export type FanAxisMode = 'composite' | 'indicator'

export type FanAxisMetric =
  | { mode: 'indicator'; indicatorId: IndicatorId; baseline: number; sigma: number }
  | { mode: 'composite'; baselines: Baselines; subject: Subject }

export function fanAxisMetric(
  mode: FanAxisMode,
  indicatorId: IndicatorId,
  baselines: Baselines,
  subject: Subject,
): FanAxisMetric {
  if (mode === 'composite') return { mode: 'composite', baselines, subject }
  return {
    mode: 'indicator',
    indicatorId,
    baseline: baselines[indicatorId],
    sigma: INDICATOR_BY_ID[indicatorId].sigma,
  }
}

export function fanAxisMetricScale(
  result: RunResult,
  metric: FanAxisMetric,
): { baseline: number; sigma: number } {
  if (metric.mode === 'indicator') {
    return { baseline: metric.baseline, sigma: metric.sigma }
  }
  return {
    baseline: cohortMedianPanelBurden(result, 0, metric.baselines, metric.subject),
    sigma: COMPOSITE_BURDEN_SIGMA,
  }
}

function metricPathValue(
  result: RunResult,
  branch: number,
  week: number,
  metric: FanAxisMetric,
): number {
  const w = Math.max(0, Math.min(HORIZON_WEEKS, week))
  const w0 = Math.floor(w)
  const w1 = Math.min(HORIZON_WEEKS, w0 + 1)
  if (metric.mode === 'composite') {
    const v0 = panelBurdenAt(result, branch, w0, metric.baselines, metric.subject)
    if (w0 === w1) return v0
    const v1 = panelBurdenAt(result, branch, w1, metric.baselines, metric.subject)
    const t = w - w0
    return v0 + (v1 - v0) * t
  }
  const pi = branchPanelIndex(metric.indicatorId)
  if (pi < 0) return 0
  const v0 = branchPanelValue(result, branch, w0, pi)
  if (w0 === w1) return v0
  const v1 = branchPanelValue(result, branch, w1, pi)
  const t = w - w0
  return v0 + (v1 - v0) * t
}

function metricCohortMedian(result: RunResult, week: number, metric: FanAxisMetric): number {
  if (metric.mode === 'composite') {
    return cohortMedianPanelBurden(result, week, metric.baselines, metric.subject)
  }
  return cohortMedianValue(result, week, metric.indicatorId)
}

/** When each lifestyle axis splits the tree (weeks along the horizon). */
export const FACTOR_FORK_WEEKS = [0, 4, 10, 18, 26] as const

/** How much lifestyle forks widen the fan on screen (0 = overlap, 1 = full fork spread). */
const LIFESTYLE_FAN_MIX = 0.52

export interface SimulationBranch extends TreeBranch {
  pickId: number
  depth: number
  opacity: number
}

function appendCurve(pts: Vec[], x0: number, y0: number, x1: number, y1: number, steps: number) {
  const seg = sampleBranch(x0, y0, x1, y1, steps)
  if (pts.length === 0) pts.push(...seg)
  else pts.push(...seg.slice(1))
}

function endValue(result: RunResult, branch: number, metric: FanAxisMetric): number {
  const stop = result.stopWeek[branch]
  const week = stop >= 0 ? stop : HORIZON_WEEKS
  return metricPathValue(result, branch, week, metric)
}

function cohortMedianValue(result: RunResult, week: number, indicatorId: IndicatorId): number {
  const pi = branchPanelIndex(indicatorId)
  if (pi < 0) return 0
  const w = Math.max(0, Math.min(HORIZON_WEEKS, Math.round(week)))
  const vals: number[] = []
  for (let b = 0; b < result.count; b += 1) {
    const stop = result.stopWeek[b]
    if (stop >= 0 && stop < w) continue
    vals.push(branchPanelValue(result, b, w, pi))
  }
  if (vals.length === 0) return 0
  vals.sort((a, b) => a - b)
  return vals[Math.floor(vals.length / 2)]
}

function pathY(
  result: RunResult,
  branch: number,
  week: number,
  spreadScale: number,
  baseline: number,
  sigma: number,
  metric: FanAxisMetric,
): number {
  const value = metricPathValue(result, branch, week, metric)
  return clampPlotY(valueToYFromBaseline(value, baseline, sigma, spreadScale))
}

function medianY(
  result: RunResult,
  week: number,
  spreadScale: number,
  baseline: number,
  sigma: number,
  metric: FanAxisMetric,
): number {
  const value = metricCohortMedian(result, week, metric)
  return clampPlotY(valueToYFromBaseline(value, baseline, sigma, spreadScale))
}

function levelNorm(levelIdx: number, levelCount: number): number {
  if (levelCount <= 1) return 0
  return (levelIdx / (levelCount - 1)) * 2 - 1
}

function branchLevelIndices(result: RunResult, branch: number): number[] {
  return FACTORS.map((_, f) => result.levels[branch * FACTORS.length + f])
}

function forkWedge(parentY: number, depth: number, spreadScale: number): number {
  const roomDown = TREE_CONTENT_BOTTOM - parentY
  const roomUp = parentY - TREE_CONTENT_TOP
  return Math.min(roomDown, roomUp) * 0.44 * 0.58 ** depth * spreadScale
}

/** Lifestyle-only geometry — spreads branches by sleep / movement / diet / stress levels. */
function buildLifestyleGeometry(
  result: RunResult,
  branch: number,
  endWeek: number,
  spreadScale: number,
): Vec[] {
  const levelIdxs = branchLevelIndices(result, branch)
  const pts: Vec[] = []
  let x = TREE_BRANCH_X
  let y = TREE_BASE_Y

  for (let depth = 0; depth < FACTORS.length; depth += 1) {
    const factor = FACTORS[depth]
    const nextWeek = Math.min(FACTOR_FORK_WEEKS[depth + 1] ?? HORIZON_WEEKS, endWeek)
    if (nextWeek <= (depth === 0 ? 0 : FACTOR_FORK_WEEKS[depth])) continue
    const nextX = treeWeekX(nextWeek)
    const norm = levelNorm(levelIdxs[depth], factor.levels.length)
    const wedge = forkWedge(y, depth, spreadScale)
    const nextY = clampPlotY(y + norm * wedge)
    appendCurve(pts, x, y, nextX, nextY, 26)
    x = nextX
    y = nextY
    if (nextWeek >= endWeek) break
  }

  if (x < treeWeekX(endWeek)) {
    appendCurve(pts, x, y, treeWeekX(endWeek), y, 20)
  }

  return pts
}

function yAtX(pts: Vec[], x: number): number {
  if (pts.length === 0) return TREE_BASE_Y
  if (x <= pts[0].x) return pts[0].y
  const last = pts[pts.length - 1]
  if (x >= last.x) return last.y
  for (let i = 0; i < pts.length - 1; i += 1) {
    const a = pts[i]
    const b = pts[i + 1]
    if (x >= a.x && x <= b.x) {
      const t = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x)
      return a.y + (b.y - a.y) * t
    }
  }
  return last.y
}

function lifestyleSpreadAt(geoPts: Vec[], week: number): number {
  const x = treeWeekX(week)
  const geoY = yAtX(geoPts, x)
  return (geoY - TREE_BASE_Y) * LIFESTYLE_FAN_MIX
}

/** Sampling step in weeks — finer when the viewport is zoomed in. */
function pathWeekStep(endWeek: number, visibleSpanWeeks = endWeek): number {
  if (visibleSpanWeeks <= 1 / 7) return 1 / 28
  if (visibleSpanWeeks <= 2 / 7) return 1 / 7
  if (visibleSpanWeeks <= 2) return 0.25
  if (endWeek <= 52) return 1
  if (endWeek <= 156) return 2
  return 4
}

function appendSimWeeks(
  pts: Vec[],
  result: RunResult,
  index: number,
  fromWeek: number,
  toWeek: number,
  geoPts: Vec[],
  spreadScale: number,
  baseline: number,
  sigma: number,
  visibleSpanWeeks: number,
  metric: FanAxisMetric,
) {
  const step = pathWeekStep(toWeek, visibleSpanWeeks)
  let x = treeWeekX(fromWeek)
  let y = mergedY(result, index, fromWeek, geoPts, spreadScale, baseline, sigma, metric)
  for (let w = fromWeek + step; w <= toWeek + step * 0.01; w += step) {
    const week = Math.min(toWeek, w)
    const nextX = treeWeekX(week)
    const nextY = mergedY(result, index, week, geoPts, spreadScale, baseline, sigma, metric)
    appendCurve(pts, x, y, nextX, nextY, step < 0.5 ? 4 : step > 2 ? 8 : 6)
    x = nextX
    y = nextY
    if (week >= toWeek) break
  }
}

function mergedY(
  result: RunResult,
  branch: number,
  week: number,
  geoPts: Vec[],
  spreadScale: number,
  baseline: number,
  sigma: number,
  metric: FanAxisMetric,
): number {
  const simY = pathY(result, branch, week, spreadScale, baseline, sigma, metric)
  return clampPlotY(simY + lifestyleSpreadAt(geoPts, week))
}

/**
 * Simulated trajectories for the active fan metric, with lifestyle forks
 * widening the fan so all branches stay visible for research.
 */
export function buildSimulationTree(
  result: RunResult,
  cursorWeek: number,
  indices: number[],
  metric: FanAxisMetric,
  fanSpread = 1,
  visibleSpanWeeks = HORIZON_WEEKS,
): SimulationBranch[] {
  const spreadScale = Math.max(1, fanSpread)
  const { baseline, sigma } = fanAxisMetricScale(result, metric)

  const ranked = indices
    .map((index) => ({ index, end: endValue(result, index, metric) }))
    .sort((a, b) => a.end - b.end)
  const rankOf = new Map(ranked.map(({ index }, rank) => [index, rank]))

  return indices.map((index) => {
    const stop = result.stopWeek[index]
    const endWeek = stop >= 0 ? stop : HORIZON_WEEKS
    const evalWeek = Math.min(WEEKS - 1, Math.round(cursorWeek))
    const outcome = branchOutcome(result, index, evalWeek)
    const pathOutcome = branchPathOutcome(result, index, cursorWeek)
    const rank = rankOf.get(index) ?? 0
    const geoPts = buildLifestyleGeometry(result, index, endWeek, spreadScale)

    const pts: Vec[] = []
    let x = TREE_ROOT_X
    let y = TREE_BASE_Y

    const y0 = mergedY(result, index, 0, geoPts, spreadScale, baseline, sigma, metric)
    appendCurve(pts, x, y, TREE_BRANCH_X, y0, 16)
    x = TREE_BRANCH_X
    y = y0

    appendSimWeeks(
      pts,
      result,
      index,
      0,
      endWeek,
      geoPts,
      spreadScale,
      baseline,
      sigma,
      visibleSpanWeeks,
      metric,
    )

    const endY = mergedY(result, index, endWeek, geoPts, spreadScale, baseline, sigma, metric)

    if (stop < 0 && endWeek < PIPELINE_MAX_WEEKS) {
      const w0 = Math.max(0, endWeek - 6)
      const v0 = metricPathValue(result, index, w0, metric)
      const v1 = metricPathValue(result, index, endWeek, metric)
      const slope = (v1 - v0) / Math.max(1, endWeek - w0)
      const tailValue = Math.max(0, v1 + slope * (PIPELINE_MAX_WEEKS - endWeek) * 0.35)
      const tailSimY = valueToYFromBaseline(tailValue, baseline, sigma, spreadScale)
      const tailSpread = lifestyleSpreadAt(geoPts, endWeek)
      const tailY = clampPlotY(tailSimY + tailSpread)
      const last = pts[pts.length - 1]
      appendCurve(pts, last.x, last.y, treeWeekX(PIPELINE_MAX_WEEKS), tailY, 28)
    }

    return {
      index,
      pickId: index,
      depth: FACTORS.length,
      opacity: 0.55 + (rank / Math.max(1, ranked.length - 1)) * 0.45,
      mid: '',
      outer: '',
      inner: '',
      upper: '',
      lower: '',
      midPts: pts,
      color: '',
      outcome,
      pathOutcome,
      stop,
      endY,
      delay: 0.06 + (rank / Math.max(1, ranked.length - 1)) * 0.65,
    }
  })
}

/** Median cohort path for the active fan metric (no lifestyle spread). */
export function buildSimulationMedian(
  result: RunResult,
  metric: FanAxisMetric,
  fanSpread = 1,
  visibleSpanWeeks = HORIZON_WEEKS,
): Vec[] {
  const spreadScale = Math.max(1, fanSpread)
  const { baseline, sigma } = fanAxisMetricScale(result, metric)

  const pts: Vec[] = []
  let x = TREE_ROOT_X
  let y = TREE_BASE_Y

  const y0 = medianY(result, 0, spreadScale, baseline, sigma, metric)
  appendCurve(pts, x, y, TREE_BRANCH_X, y0, 16)
  x = TREE_BRANCH_X
  y = y0

  const step = pathWeekStep(HORIZON_WEEKS, visibleSpanWeeks)
  for (let w = step; w <= HORIZON_WEEKS + step * 0.01; w += step) {
    const week = Math.min(HORIZON_WEEKS, w)
    const nextX = treeWeekX(week)
    const nextY = medianY(result, week, spreadScale, baseline, sigma, metric)
    appendCurve(pts, x, y, nextX, nextY, step < 0.5 ? 4 : 8)
    x = nextX
    y = nextY
    if (week >= HORIZON_WEEKS) break
  }

  if (PIPELINE_MAX_WEEKS > HORIZON_WEEKS) {
    const p50Start = metricCohortMedian(result, Math.max(0, HORIZON_WEEKS - 6), metric)
    const p50End = metricCohortMedian(result, HORIZON_WEEKS, metric)
    const slope = (p50End - p50Start) / 6
    const tailValue = Math.max(0, p50End + slope * (PIPELINE_MAX_WEEKS - HORIZON_WEEKS) * 0.35)
    const tailY = clampPlotY(valueToYFromBaseline(tailValue, baseline, sigma, spreadScale))
    appendCurve(pts, x, y, treeWeekX(PIPELINE_MAX_WEEKS), tailY, 24)
  }

  return pts
}

export function forkWeekXs(): number[] {
  return [...FACTOR_FORK_WEEKS, HORIZON_WEEKS]
}
