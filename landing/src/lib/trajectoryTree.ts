import { HORIZON_WEEKS } from '../engine/model'
import { WEEKS, type RunResult } from '../engine/cohort'
import type { Vec } from './curve'
import { sampleBranch, toBand, toPath } from './curve'

/** Shared layout with the hero probability tree (1440×460 instrument plate). */
export const TREE_W = 1440
export const TREE_H = 460
export const TREE_BASE_Y = 250
export const TREE_TRUNK_X0 = 64
export const TREE_BRANCH_X = 616
export const TREE_END_X = 1236
export const TREE_AXIS_Y = 420
export const TREE_PLOT_TOP = 78
export const TREE_PX_PER_WEEK = (TREE_END_X - TREE_BRANCH_X) / HORIZON_WEEKS

/** Vertical drawable band for branch terminals (keeps fan inside the plate). */
export const TREE_CONTENT_TOP = TREE_PLOT_TOP + 28
export const TREE_CONTENT_BOTTOM = TREE_AXIS_Y - 24

export const treeWeekX = (week: number) => TREE_BRANCH_X + week * TREE_PX_PER_WEEK

/** Map a simulated analyte value into the fan's vertical band (higher values → top). */
export function valueToY(value: number, lo: number, hi: number, spreadScale = 1): number {
  const span = TREE_AXIS_Y - TREE_PLOT_TOP - 48
  const t = (value - lo) / (hi - lo || 1)
  return TREE_BASE_Y + (0.5 - t) * span * spreadScale
}

/**
 * Fan Y relative to this subject's baseline — week 0 stays put when protocol changes.
 * Higher analyte values plot toward the top of the band.
 */
export function valueToYFromBaseline(
  value: number,
  baseline: number,
  sigma: number,
  spreadScale = 1,
): number {
  const span = (TREE_AXIS_Y - TREE_PLOT_TOP - 48) * spreadScale
  const z = (value - baseline) / (sigma || 1)
  return TREE_BASE_Y - z * span * 0.11
}

export function clampPlotY(y: number): number {
  return Math.min(TREE_CONTENT_BOTTOM, Math.max(TREE_CONTENT_TOP, y))
}

const OUTCOME_BAND = 0.1

export function branchOutcome(result: RunResult, branch: number, week: number) {
  const stop = result.stopWeek[branch]
  if (stop >= 0 && stop <= week) return 'stopped' as const
  const gain = result.baselineScore - result.scores[branch * WEEKS + Math.round(week)]
  if (gain > OUTCOME_BAND) return 'improved' as const
  if (gain < -OUTCOME_BAND) return 'worsened' as const
  return 'flat' as const
}

/** Color the lived path by the trend *before* an acute stop — not the terminal stop state. */
export function branchPathOutcome(result: RunResult, branch: number, cursorWeek: number) {
  const stop = result.stopWeek[branch]
  const week = Math.min(WEEKS - 1, Math.round(cursorWeek))
  if (stop >= 0 && stop <= week) {
    return branchOutcome(result, branch, Math.max(0, stop - 1))
  }
  return branchOutcome(result, branch, week)
}

/** Evenly cover the cohort rank range without drawing every branch. */
export function sampleBranchIndices(count: number, max = 28): number[] {
  if (count <= max) return Array.from({ length: count }, (_, i) => i)
  const out = new Set<number>()
  for (let i = 0; i < max; i += 1) {
    out.add(Math.floor((i * (count - 1)) / (max - 1)))
  }
  return [...out]
}

export interface TreeBranch {
  index: number
  mid: string
  outer: string
  inner: string
  upper: string
  lower: string
  midPts: Vec[]
  color: string
  outcome: ReturnType<typeof branchOutcome>
  /** Outcome used to colour the lived segment before an acute stop. */
  pathOutcome?: ReturnType<typeof branchOutcome>
  stop: number
  endY: number
  delay: number
}

const COLOR = {
  improved: 'var(--branch-a)',
  flat: 'var(--branch-b)',
  worsened: 'var(--branch-c)',
  stopped: 'var(--ink-ghost)',
} as const

function endValue(result: RunResult, branch: number): number {
  const stop = result.stopWeek[branch]
  const week = stop >= 0 ? stop : HORIZON_WEEKS
  return result.paths[branch * WEEKS + week]
}

/**
 * Map cohort terminals into hero-style S-curves.
 *
 * `fanSpread` widens the vertical fan so individual probabilities can be
 * picked without magnifying labels on the trunk.
 */
export function buildTreeBranches(
  result: RunResult,
  cursorWeek: number,
  indices: number[],
  fanSpread = 1,
): TreeBranch[] {
  const ranked = indices
    .map((index) => ({ index, end: endValue(result, index) }))
    .sort((a, b) => a.end - b.end)

  const span = TREE_AXIS_Y - TREE_PLOT_TOP - 48
  const n = ranked.length
  const spreadScale = Math.max(1, fanSpread)

  return ranked.map(({ index }, rank) => {
    const stop = result.stopWeek[index]
    const endWeek = stop >= 0 ? stop : HORIZON_WEEKS
    const endX = treeWeekX(endWeek)
    const t = n > 1 ? rank / (n - 1) : 0.5
    const endY = TREE_BASE_Y + (0.5 - t) * span * spreadScale
    const evalWeek = Math.max(cursorWeek, Math.min(endWeek, HORIZON_WEEKS))
    const outcome = branchOutcome(result, index, evalWeek)
    const ribbon = (outcome === 'improved' ? 24 : 18) * Math.sqrt(spreadScale)

    const midPts = sampleBranch(TREE_BRANCH_X, TREE_BASE_Y, endX, endY, 56)

    const widen = (p: { x: number; y: number }, sign: number) => ({
      x: p.x,
      y: p.y + sign * ribbon * Math.pow((p.x - TREE_BRANCH_X) / (endX - TREE_BRANCH_X || 1), 1.35),
    })
    const outerUp = midPts.map((p) => widen(p, -1))
    const outerDown = midPts.map((p) => widen(p, 1))
    const innerUp = midPts.map((p) => widen(p, -0.42))
    const innerDown = midPts.map((p) => widen(p, 0.42))

    return {
      index,
      mid: toPath(midPts),
      outer: toBand(outerUp, outerDown),
      inner: toBand(innerUp, innerDown),
      upper: toPath(outerUp),
      lower: toPath(outerDown),
      midPts,
      color: COLOR[outcome],
      outcome,
      stop,
      endY,
      delay: 0.08 + t * 0.7,
    }
  })
}

export function weekFromTreeX(px: number): number {
  const week = (px - TREE_BRANCH_X) / TREE_PX_PER_WEEK
  return Math.max(0, Math.min(HORIZON_WEEKS, Math.round(week * 2) / 2))
}

/** Smooth median curve through the fan — same geometry as branches, terminal at horizon p50. */
export function buildMedianPoints(
  result: RunResult,
  fanSpread = 1,
): Vec[] {
  const [lo, hi] = result.domain
  const span = TREE_AXIS_Y - TREE_PLOT_TOP - 48
  const spreadScale = Math.max(1, fanSpread)
  const p50 = result.stats[HORIZON_WEEKS].p50
  const t = (p50 - lo) / (hi - lo || 1)
  const endY = TREE_BASE_Y + (0.5 - t) * span * spreadScale
  return sampleBranch(TREE_BRANCH_X, TREE_BASE_Y, treeWeekX(HORIZON_WEEKS), endY, 56)
}
