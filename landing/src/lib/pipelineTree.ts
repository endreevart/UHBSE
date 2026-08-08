import { HORIZON_WEEKS } from '../engine/model'
import { WEEKS, type RunResult } from '../engine/cohort'
import type { Vec } from './curve'
import { sampleBranch } from './curve'
import {
  TREE_AXIS_Y,
  TREE_BASE_Y,
  TREE_BRANCH_X,
  TREE_PLOT_TOP,
  branchOutcome,
  buildTreeBranches,
  treeWeekX,
  valueToY,
  type TreeBranch,
} from './trajectoryTree'

/** Display horizon matches the cohort engine (no extrapolation tail). */
export const PIPELINE_MAX_WEEKS = HORIZON_WEEKS
export const PIPELINE_FORK_INTERVAL = 12
export const PIPELINE_SUBFORKS = 3
/** Max parent lines that spawn sub-branches at each checkpoint (keeps WebGL fast). */
export const PIPELINE_FORK_SAMPLE = 48
export const PIPELINE_MAX_GENERATIONS = 8

export interface PipelineBranch extends TreeBranch {
  /** Stable pick id — maps to root cohort branch for biomarker readout. */
  pickId: number
  generation: number
  forkWeek: number
  opacity: number
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

function ptAtX(pts: Vec[], x: number): Vec | null {
  if (pts.length < 2) return null
  for (let i = 0; i < pts.length - 1; i += 1) {
    const a = pts[i]
    const b = pts[i + 1]
    if (x >= a.x && x <= b.x) {
      const t = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x)
      return { x, y: a.y + (b.y - a.y) * t }
    }
  }
  return null
}

function pathValueAt(result: RunResult, branch: number, week: number): number {
  const w = clamp(Math.round(week), 0, HORIZON_WEEKS)
  return result.paths[branch * WEEKS + w]
}

/** Linear trend from the last simulated segment, for weeks beyond HORIZON_WEEKS. */
function extrapolateValue(result: RunResult, branch: number, week: number): number {
  if (week <= HORIZON_WEEKS) return pathValueAt(result, branch, week)
  const w0 = Math.max(0, HORIZON_WEEKS - 6)
  const v0 = pathValueAt(result, branch, w0)
  const v1 = pathValueAt(result, branch, HORIZON_WEEKS)
  const slope = (v1 - v0) / Math.max(1, HORIZON_WEEKS - w0)
  const fade = 0.92 ** ((week - HORIZON_WEEKS) / PIPELINE_FORK_INTERVAL)
  return Math.max(0, v1 + slope * (week - HORIZON_WEEKS) * fade)
}

function valueToYLocal(
  value: number,
  lo: number,
  hi: number,
  spreadScale: number,
): number {
  return valueToY(value, lo, hi, spreadScale)
}

function statsY(
  result: RunResult,
  week: number,
  quantile: 'p05' | 'p50' | 'p95',
  spreadScale: number,
): number {
  const w = clamp(Math.round(week), 0, HORIZON_WEEKS)
  const [lo, hi] = result.domain
  const v = result.stats[w][quantile]
  return valueToYLocal(v, lo, hi, spreadScale)
}

function sampleParents(lines: PipelineBranch[], week: number, cap: number): PipelineBranch[] {
  const x = treeWeekX(week)
  const alive = lines.filter((ln) => {
    const last = ln.midPts[ln.midPts.length - 1]
    return last.x >= x - 2 && (ln.stop < 0 || ln.stop > week)
  })
  if (alive.length <= cap) return alive
  const out: PipelineBranch[] = []
  for (let i = 0; i < cap; i += 1) {
    out.push(alive[Math.floor((i * (alive.length - 1)) / (cap - 1))])
  }
  return out
}

function spawnSubBranches(
  parent: PipelineBranch,
  forkWeek: number,
  endWeek: number,
  result: RunResult,
  cursorWeek: number,
  spreadScale: number,
  generation: number,
): PipelineBranch[] {
  const forkX = treeWeekX(forkWeek)
  const forkPt = ptAtX(parent.midPts, forkX)
  if (!forkPt) return []

  const endX = treeWeekX(endWeek)
  const quantiles: Array<'p05' | 'p50' | 'p95'> = ['p05', 'p50', 'p95']
  const ribbon = 14 * Math.sqrt(spreadScale)

  return quantiles.map((q, k) => {
    const endY =
      endWeek <= HORIZON_WEEKS
        ? statsY(result, endWeek, q, spreadScale)
        : valueToYLocal(extrapolateValue(result, parent.pickId, endWeek), result.domain[0], result.domain[1], spreadScale)
    const jitter = (k - 1) * ribbon * 0.35
    const midPts = sampleBranch(forkPt.x, forkPt.y, endX, endY + jitter, 48)
    const evalWeek = clamp(cursorWeek, forkWeek, endWeek)
    const outcome = branchOutcome(result, parent.pickId, Math.min(evalWeek, HORIZON_WEEKS))

    return {
      index: parent.pickId,
      pickId: parent.pickId,
      generation,
      forkWeek,
      opacity: Math.max(0.22, 0.92 - generation * 0.1),
      mid: '',
      outer: '',
      inner: '',
      upper: '',
      lower: '',
      midPts,
      color: parent.color,
      outcome,
      stop: parent.stop,
      endY: endY + jitter,
      delay: parent.delay + generation * 0.08,
    }
  })
}

/**
 * Build the full pipeline fan: root lifestyle branches plus sub-forks at every
 * 12-week checkpoint (branches of branches), extrapolated out to PIPELINE_MAX_WEEKS.
 */
export function buildPipelineBranches(
  result: RunResult,
  cursorWeek: number,
  rootIndices: number[],
  fanSpread = 1,
): PipelineBranch[] {
  const spreadScale = Math.max(1, fanSpread)
  const roots = buildTreeBranches(result, cursorWeek, rootIndices, fanSpread).map((br) => ({
    ...br,
    pickId: br.index,
    generation: 0,
    forkWeek: 0,
    opacity: 1,
  }))

  let frontier: PipelineBranch[] = roots

  for (
    let forkWeek = PIPELINE_FORK_INTERVAL;
    forkWeek < PIPELINE_MAX_WEEKS && frontier.length > 0;
    forkWeek += PIPELINE_FORK_INTERVAL
  ) {
    const generation = forkWeek / PIPELINE_FORK_INTERVAL
    if (generation > PIPELINE_MAX_GENERATIONS) break

    const endWeek = Math.min(forkWeek + PIPELINE_FORK_INTERVAL, PIPELINE_MAX_WEEKS)
    const parents = sampleParents(frontier, forkWeek, PIPELINE_FORK_SAMPLE)
    const children: PipelineBranch[] = []

    for (const parent of parents) {
      children.push(...spawnSubBranches(parent, forkWeek, endWeek, result, cursorWeek, spreadScale, generation))
    }

    if (children.length === 0) break
    frontier = children
    roots.push(...children)
  }

  return roots
}

/** Median trunk through the pipeline — observed segment + extrapolated tail. */
export function buildPipelineMedian(
  result: RunResult,
  fanSpread = 1,
): Vec[] {
  const spreadScale = Math.max(1, fanSpread)
  const [lo, hi] = result.domain
  const span = TREE_AXIS_Y - TREE_PLOT_TOP - 48
  const p50End = result.stats[HORIZON_WEEKS].p50
  const tEnd = (p50End - lo) / (hi - lo || 1)
  const endY36 = TREE_BASE_Y + (0.5 - tEnd) * span * spreadScale

  const observed = sampleBranch(TREE_BRANCH_X, TREE_BASE_Y, treeWeekX(HORIZON_WEEKS), endY36, 56)

  const p50Start = result.stats[Math.max(0, HORIZON_WEEKS - 6)].p50
  const slope = (p50End - p50Start) / 6
  const tailValue = Math.max(0, p50End + slope * (PIPELINE_MAX_WEEKS - HORIZON_WEEKS) * 0.35)
  const tTail = (tailValue - lo) / (hi - lo || 1)
  const tailEndY = TREE_BASE_Y + (0.5 - tTail) * span * spreadScale

  const tail = sampleBranch(
    treeWeekX(HORIZON_WEEKS),
    observed[observed.length - 1].y,
    treeWeekX(PIPELINE_MAX_WEEKS),
    tailEndY,
    48,
  )

  return [...observed.slice(0, -1), ...tail]
}

export function pipelineWeekFromX(px: number): number {
  const week = (px - TREE_BRANCH_X) / ((treeWeekX(1) - TREE_BRANCH_X))
  return Math.max(0, Math.min(PIPELINE_MAX_WEEKS, Math.round(week * 2) / 2))
}
