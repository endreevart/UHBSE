import { HORIZON_WEEKS, INDICATOR_BY_ID } from '../engine/model'
import {
  WEEKS,
  branchPanelIndex,
  branchPanelValue,
  type RunResult,
} from '../engine/cohort'
import { referenceFor, SNAPSHOT_PANEL, type Baselines, type Subject } from '../engine/subject'

function excursion(
  value: number,
  range: [number, number] | undefined,
  sigma: number,
): number {
  if (!range) return 0
  if (value > range[1]) return (value - range[1]) / sigma
  if (value < range[0]) return (range[0] - value) / sigma
  return 0
}

/** Average reference-interval burden across the full snapshot panel at one week. */
export function panelBurdenAt(
  result: RunResult,
  branch: number,
  week: number,
  baselines: Baselines,
  subject: Subject,
): number {
  const w = Math.max(0, Math.min(WEEKS - 1, Math.round(week)))
  let total = 0
  for (const id of SNAPSHOT_PANEL) {
    const pi = branchPanelIndex(id)
    const value = branchPanelValue(result, branch, w, pi)
    const sigma = INDICATOR_BY_ID[id].sigma || 1
    const range = referenceFor(subject, id)
    const refExc = excursion(value, range, sigma)
    const drift = Math.abs(value - baselines[id]) / sigma * 0.12
    total += refExc + drift
  }
  return total / SNAPSHOT_PANEL.length
}

/** Cohort median of full-panel burden among branches still active at `week`. */
export function cohortMedianPanelBurden(
  result: RunResult,
  week: number,
  baselines: Baselines,
  subject: Subject,
): number {
  const w = Math.max(0, Math.min(WEEKS - 1, Math.round(week)))
  const vals: number[] = []
  for (let b = 0; b < result.count; b += 1) {
    const stop = result.stopWeek[b]
    if (stop >= 0 && stop < w) continue
    vals.push(panelBurdenAt(result, b, w, baselines, subject))
  }
  if (vals.length === 0) return 0
  vals.sort((a, b) => a - b)
  return vals[Math.floor(vals.length / 2)]
}

export function branchTerminalWeek(result: RunResult, branch: number): number {
  const stop = result.stopWeek[branch]
  return stop >= 0 ? stop : HORIZON_WEEKS
}

/**
 * Lifestyle branch with the lowest full-panel burden at its terminal week.
 * Considers every snapshot marker, not only the fan axis indicator.
 */
export function pickBestBranch(result: RunResult, baselines: Baselines, subject: Subject): number {
  let best = 0
  let bestScore = Infinity
  for (let b = 0; b < result.count; b += 1) {
    const w = branchTerminalWeek(result, b)
    const score = panelBurdenAt(result, b, w, baselines, subject)
    if (score < bestScore) {
      bestScore = score
      best = b
    }
  }
  return best
}
