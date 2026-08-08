import { INDICATOR_BY_ID, type IndicatorId } from '../engine/model'
import {
  FACTORS,
  VITALS,
  WEEKS,
  branchPanelValue,
  type Outcome,
  type RunResult,
} from '../engine/cohort'
import { SNAPSHOT_PANEL } from '../engine/subject'
import { isSenescenceStop } from '../engine/mortality'
import { branchOutcome } from './trajectoryTree'

export type FactorTier = 'poor' | 'moderate' | 'good'

export interface PanelDelta {
  id: IndicatorId
  baseline: number
  end: number
  delta: number
  sigmaNorm: number
}

export interface BranchSummary {
  week: number
  outcome: Outcome
  stopWeek: number
  scoreGain: number
  percentile: number
  factors: { id: (typeof FACTORS)[number]['id']; tier: FactorTier; value: number }[]
  panel: PanelDelta[]
  improved: PanelDelta[]
  worsened: PanelDelta[]
}

function factorTier(value: number): FactorTier {
  if (value <= -0.4) return 'poor'
  if (value >= 0.4) return 'good'
  return 'moderate'
}

function branchScorePercentile(result: RunResult, branch: number, week: number): number {
  const val = result.scores[branch * WEEKS + week]
  let below = 0
  let live = 0
  for (let b = 0; b < result.count; b++) {
    const stop = result.stopWeek[b]
    if (stop >= 0 && stop < week) continue
    live += 1
    if (result.scores[b * WEEKS + week] > val) below += 1
  }
  if (live <= 1) return 50
  return Math.round((below / (live - 1)) * 100)
}

function panelDeltas(
  result: RunResult,
  branch: number,
  week: number,
  baselines: Record<IndicatorId, number>,
): PanelDelta[] {
  return SNAPSHOT_PANEL.map((id, p) => {
    const baseline = baselines[id]
    const end = branchPanelValue(result, branch, week, p)
    const delta = end - baseline
    const sigma = INDICATOR_BY_ID[id].sigma || 1
    return { id, baseline, end, delta, sigmaNorm: delta / sigma }
  })
}

export function summarizeBranch(
  result: RunResult,
  branch: number,
  cursorWeek: number,
  baselines: Record<IndicatorId, number>,
): BranchSummary {
  const week = Math.min(WEEKS - 1, Math.round(cursorWeek))
  const outcome = branchOutcome(result, branch, week)
  const scoreGain = result.baselineScore - result.scores[branch * WEEKS + week]
  const panel = panelDeltas(result, branch, week, baselines)

  const improved = [...panel]
    .filter((row) => row.sigmaNorm < -0.08)
    .sort((a, b) => a.sigmaNorm - b.sigmaNorm)
    .slice(0, 4)
  const worsened = [...panel]
    .filter((row) => row.sigmaNorm > 0.08)
    .sort((a, b) => b.sigmaNorm - a.sigmaNorm)
    .slice(0, 4)

  return {
    week,
    outcome,
    stopWeek: result.stopWeek[branch],
    scoreGain,
    percentile: branchScorePercentile(result, branch, week),
    factors: FACTORS.map((factor, fi) => {
      const value = factor.levels[result.levels[branch * FACTORS.length + fi]]
      return { id: factor.id, tier: factorTier(value), value }
    }),
    panel,
    improved,
    worsened,
  }
}

export function stopVitalId(result: RunResult, branch: number): IndicatorId | null {
  const reason = result.stopReason[branch]
  if (reason < 0 || isSenescenceStop(reason)) return null
  return VITALS[reason]?.id ?? null
}

export function isSenescenceBranchStop(result: RunResult, branch: number): boolean {
  return isSenescenceStop(result.stopReason[branch])
}

export function passesOutcomeFilter(
  outcome: Outcome,
  showFavorable: boolean,
  showUnfavorable: boolean,
): boolean {
  if (outcome === 'improved') return showFavorable
  if (outcome === 'stopped' || outcome === 'worsened') return showUnfavorable
  return showFavorable || showUnfavorable
}
