import {
  HORIZON_WEEKS,
  INDICATORS,
  INDICATOR_BY_ID,
  INTERVENTIONS,
  INTERVENTION_ORDER,
  isControl,
  simulate,
  toSigma,
  type AppliedIntervention,
  type EffectRow,
  type IndicatorId,
  type InterventionId,
  type Scenario,
} from './model'
import type { SystemId } from './indicators'
import { VITALS } from './cohort'
import { referenceFor, type Baselines, type Subject } from './subject'

/**
 * The scenario graph.
 *
 * The trajectory view answers what a protocol does. This module answers the
 * questions that turn a set of curves into a scenario you can navigate: where
 * did this branch separate from its parent, what change caused it, which
 * intervention is responsible for the number on screen right now, and what
 * eventually ends the branch.
 *
 * Everything here is model attribution over the engine's own additive effect
 * terms. It is not a causal claim about biology, and the interface has to keep
 * saying so.
 */

/* -------------------------------------------------------------- lineage */

export interface BranchNode {
  scenario: Scenario
  parent: Scenario | null
  children: BranchNode[]
  /** distance from the control */
  depth: number
  /** vertical slot in the map, assigned so no two branches overlap */
  row: number
}

export interface BranchTree {
  roots: BranchNode[]
  /** every node in draw order, top row first */
  flat: BranchNode[]
  rows: number
}

/**
 * Arrange the scenarios into the tree they already describe.
 *
 * `parentId` and `branchWeek` have been on every scenario from the start; until
 * now nothing drew them, so a branch looked like a result rather than a path.
 */
export function branchTree(scenarios: Scenario[]): BranchTree {
  const byId = new Map(scenarios.map((s) => [s.id, s]))
  const nodes = new Map<string, BranchNode>(
    scenarios.map((s) => [
      s.id,
      { scenario: s, parent: s.parentId ? (byId.get(s.parentId) ?? null) : null, children: [], depth: 0, row: 0 },
    ]),
  )

  const roots: BranchNode[] = []
  for (const node of nodes.values()) {
    const parent = node.scenario.parentId ? nodes.get(node.scenario.parentId) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }

  // children sorted by the week they left, so the map reads left to right
  for (const node of nodes.values()) {
    node.children.sort((a, b) => a.scenario.branchWeek - b.scenario.branchWeek)
  }

  const flat: BranchNode[] = []
  let row = 0
  const walk = (node: BranchNode, depth: number) => {
    node.depth = depth
    node.row = row
    row += 1
    flat.push(node)
    for (const child of node.children) walk(child, depth + 1)
  }
  for (const root of roots) walk(root, 0)

  return { roots, flat, rows: row }
}

/* ------------------------------------------------------------ divergence */

export type EventKind = 'added' | 'removed' | 'raised' | 'lowered'

export interface ProtocolEvent {
  week: number
  spec: InterventionId
  kind: EventKind
  from?: number
  to?: number
}

const doseAt = (list: AppliedIntervention[], spec: InterventionId, week: number): number => {
  const segments = list
    .filter((iv) => iv.spec === spec && iv.startWeek <= week)
    .sort((a, b) => a.startWeek - b.startWeek)
  const last = segments[segments.length - 1]
  if (!last) return 0
  if (last.endWeek !== undefined && week > last.endWeek) return 0
  return last.dose
}

/**
 * Every point at which a protocol changes, in time order.
 *
 * These are what the branch map hangs its labels on: a branch is not simply a
 * different arm, it is the consequence of a specific change at a specific week.
 */
export function protocolEvents(scenario: Scenario): ProtocolEvent[] {
  const events: ProtocolEvent[] = []
  for (const spec of INTERVENTION_ORDER) {
    const segments = scenario.interventions
      .filter((iv) => iv.spec === spec)
      .sort((a, b) => a.startWeek - b.startWeek)
    segments.forEach((seg, i) => {
      const previous = segments[i - 1]
      if (!previous) {
        if (seg.dose > 0) events.push({ week: seg.startWeek, spec, kind: 'added', to: seg.dose })
        return
      }
      if (seg.dose === previous.dose) return
      events.push({
        week: seg.startWeek,
        spec,
        kind: seg.dose === 0 ? 'removed' : seg.dose > previous.dose ? 'raised' : 'lowered',
        from: previous.dose,
        to: seg.dose,
      })
    })
  }
  return events.sort((a, b) => a.week - b.week)
}

/**
 * What separated a branch from its parent.
 *
 * Read at the branch week rather than over the whole horizon: later changes are
 * this branch's own history, not the reason it exists.
 */
export function divergence(scenario: Scenario, parent: Scenario | null): ProtocolEvent[] {
  if (!parent) return []
  const week = scenario.branchWeek
  const out: ProtocolEvent[] = []
  for (const spec of INTERVENTION_ORDER) {
    const before = doseAt(parent.interventions, spec, week)
    const after = doseAt(scenario.interventions, spec, week)
    if (before === after) continue
    out.push({
      week,
      spec,
      kind: before === 0 ? 'added' : after === 0 ? 'removed' : after > before ? 'raised' : 'lowered',
      from: before,
      to: after,
    })
  }
  return out
}

/**
 * What one branch does that another does not, as of the given week.
 *
 * The event is dated to the change that produced the difference, not to where
 * the playhead happens to be. "Why these two differ" is a fact about the
 * protocol; it does not move when you scrub.
 */
export function protocolDiff(a: Scenario, b: Scenario, week: number): ProtocolEvent[] {
  const out: ProtocolEvent[] = []
  for (const spec of INTERVENTION_ORDER) {
    const left = doseAt(a.interventions, spec, week)
    const right = doseAt(b.interventions, spec, week)
    if (left === right) continue
    const starts = [...a.interventions, ...b.interventions]
      .filter((iv) => iv.spec === spec && iv.startWeek <= week)
      .map((iv) => iv.startWeek)
    out.push({
      week: starts.length > 0 ? Math.max(...starts) : Math.floor(week),
      spec,
      kind: right === 0 ? 'added' : left === 0 ? 'removed' : left > right ? 'raised' : 'lowered',
      from: right,
      to: left,
    })
  }
  return out.sort((x, y) => x.week - y.week)
}

/* ----------------------------------------------------------- termination */

const CRITICAL_SLACK = 1.6
const HAZARD_CARRY = 0.72
const CRITICAL_HAZARD = 2.9

export interface BranchStatus {
  /** week the branch stops being viable, or -1 if it reaches the horizon */
  stopWeek: number
  stopReason: IndicatorId | null
}

/**
 * Off-target load carried by a protocol at one week.
 *
 * `simulate` models only the intended effect, which is enough to draw a
 * trajectory but not to decide whether a branch survives: what ends branches is
 * the load that grows with the square of the dose against the maximum. The
 * cohort has always applied it. A named branch has to be the neutral centre of
 * its own cohort rather than a curve that never pays the cost, or the map and
 * the counters disagree about what a protocol does.
 */
function adverseAt(scenario: Scenario, indicatorId: IndicatorId, week: number): number {
  let load = 0
  for (const iv of scenario.interventions) {
    if (iv.dose <= 0) continue
    const spec = INTERVENTIONS[iv.spec]
    const effect = spec.adverse?.[indicatorId]
    if (!effect) continue
    if (week <= iv.startWeek) continue
    const closed = iv.endWeek !== undefined && week > iv.endWeek
    const r = closed
      ? (1 - Math.exp(-(iv.endWeek! - iv.startWeek) / spec.tau)) *
        Math.exp(-(week - iv.endWeek!) / spec.tau)
      : 1 - Math.exp(-(week - iv.startWeek) / spec.tau)
    load += effect * (iv.dose / spec.max) ** 2 * r
  }
  return load
}

/**
 * The off-target channel on the same footing as the intended one.
 *
 * `effectGrid` answers what a protocol is trying to do. This answers what it is
 * also doing, in the same shape and the same units, so both can be hung on the
 * same anatomy and compared without the viewer having to hold two mental
 * scales. Keeping them separate rather than netted is the point: a protocol
 * whose intended and unintended effects cancel to zero is not a protocol that
 * does nothing.
 */
export function adverseGrid(scenario: Scenario): EffectRow[] {
  return INDICATORS.map((indicator) => {
    const weekly: number[] = []
    let peak = 0
    for (let week = 0; week <= HORIZON_WEEKS; week += 1) {
      const e = toSigma(indicator.id, adverseAt(scenario, indicator.id, week))
      weekly.push(e)
      peak = Math.max(peak, Math.abs(e))
    }
    return { indicator, weekly, peak }
  })
}

/**
 * Run one named branch against the same stop rule the cohort uses.
 *
 * The cohort answers this thousands of times over sampled lifestyles; a named
 * branch is the deterministic centre of that, so the two have to agree on what
 * ending a branch means or the map and the counters tell different stories.
 */
export function branchStatus(
  scenario: Scenario,
  subject: Subject,
  baselines: Baselines,
): BranchStatus {
  const tracked = VITALS.map((v) => {
    const indicator = INDICATOR_BY_ID[v.id]
    const range = referenceFor(subject, v.id)
    const base = baselines[v.id]
    return {
      id: v.id,
      weight: v.weight,
      sigma: indicator.sigma,
      points: simulate(scenario, v.id, baselines).points,
      hi: range ? Math.max(range[1], base) + CRITICAL_SLACK * indicator.sigma : Infinity,
      lo: range ? Math.min(range[0], base) - CRITICAL_SLACK * indicator.sigma : -Infinity,
    }
  })

  let hazard = 0
  for (let w = 1; w <= HORIZON_WEEKS; w += 1) {
    let weekHazard = 0
    let worst: IndicatorId | null = null
    let worstLoad = 0

    for (const v of tracked) {
      const value = v.points[w * 2].value + adverseAt(scenario, v.id, w)
      const over = value > v.hi ? (value - v.hi) / v.sigma : value < v.lo ? (v.lo - value) / v.sigma : 0
      if (over <= 0) continue
      const load = over * v.weight
      weekHazard += load
      if (load > worstLoad) {
        worstLoad = load
        worst = v.id
      }
    }

    hazard = hazard * HAZARD_CARRY + weekHazard
    if (hazard > CRITICAL_HAZARD) return { stopWeek: w, stopReason: worst }
  }

  return { stopWeek: -1, stopReason: null }
}

/* ----------------------------------------------------------- attribution */

export interface Contribution {
  spec: InterventionId
  /** signed contribution in the indicator's own units */
  value: number
  /** share of the total absolute movement, 0..1 */
  share: number
}

/**
 * Which intervention is responsible for the number on screen.
 *
 * The engine's effect terms are additive, so removing one intervention and
 * re-running gives its exact contribution rather than an estimate of it. The
 * residual is reported separately instead of being folded into the largest
 * term, because a residual that stops being ~0 is a sign the model has grown a
 * non-additive path and the panel should say so rather than hide it.
 */
export function attribution(
  scenario: Scenario,
  control: Scenario,
  indicatorId: IndicatorId,
  week: number,
  baselines: Baselines,
): { rows: Contribution[]; residual: number; total: number } {
  const at = (s: Scenario) => simulate(s, indicatorId, baselines).points[Math.round(week * 2)].value
  const full = at(scenario)
  const total = full - at(control)

  const specs = [...new Set(scenario.interventions.filter((iv) => iv.dose > 0).map((iv) => iv.spec))]
  const raw = specs.map((spec) => ({
    spec,
    value: full - at({ ...scenario, interventions: scenario.interventions.filter((iv) => iv.spec !== spec) }),
  }))

  const sum = raw.reduce((acc, r) => acc + Math.abs(r.value), 0)
  const residual = total - raw.reduce((acc, r) => acc + r.value, 0)
  const scale = sum + Math.abs(residual)

  return {
    total,
    residual,
    rows: raw
      .map((r) => ({ ...r, share: scale > 0 ? Math.abs(r.value) / scale : 0 }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value)),
  }
}

/* -------------------------------------------------------------- influence */

export type Confidence = 'high' | 'medium' | 'low'

const CONFIDENCE: Record<string, Confidence> = {
  CONFIRMED: 'high',
  LIKELY: 'medium',
  UNKNOWN: 'low',
}

export interface InfluenceEdge {
  spec: InterventionId
  system: SystemId
  indicator: IndicatorId
  /** contribution at the current week, in the indicator's sigma */
  sigma: number
  confidence: Confidence
}

export interface InfluenceGraph {
  edges: InfluenceEdge[]
  specs: InterventionId[]
  systems: SystemId[]
  indicators: IndicatorId[]
  /** largest single edge, for scaling stroke widths */
  peak: number
}

/**
 * Intervention → biological system → indicator.
 *
 * `direct` reads the engine's own effect terms: what this protocol is doing to
 * this analyte at this week. `secondary` reads the off-target channel instead —
 * the load that only appears as the dose climbs, which is what makes an
 * aggressive protocol a different proposition rather than a stronger one.
 */
export function influenceGraph(
  scenario: Scenario,
  week: number,
  channel: 'direct' | 'secondary',
  limit = 6,
): InfluenceGraph {
  const active = scenario.interventions.filter((iv) => iv.dose > 0)
  const totals = new Map<string, InfluenceEdge>()

  for (const iv of active) {
    const spec = INTERVENTIONS[iv.spec]
    const table = channel === 'direct' ? spec.effects : (spec.adverse ?? {})
    const ratio = iv.dose / spec.refDose
    const elapsed = week - iv.startWeek
    if (elapsed <= 0) continue
    const closed = iv.endWeek !== undefined && week > iv.endWeek
    const r = closed
      ? (1 - Math.exp(-(iv.endWeek! - iv.startWeek) / spec.tau)) *
        Math.exp(-(week - iv.endWeek!) / spec.tau)
      : 1 - Math.exp(-elapsed / spec.tau)

    // off-target load grows with the square of the dose against the maximum,
    // which is the whole reason it is kept apart from the intended effect
    const weight = channel === 'direct' ? ratio : (iv.dose / spec.max) ** 2

    for (const key of Object.keys(table) as IndicatorId[]) {
      const effect = table[key] as number
      const sigma = toSigma(key, effect * weight * r)
      if (Math.abs(sigma) < 0.02) continue
      const id = `${iv.spec}:${key}`
      const existing = totals.get(id)
      if (existing) existing.sigma += sigma
      else
        totals.set(id, {
          spec: iv.spec,
          system: INDICATOR_BY_ID[key].system,
          indicator: key,
          sigma,
          confidence: CONFIDENCE[spec.provenance.status] ?? 'low',
        })
    }
  }

  // rank indicators by the total movement attributed to them, then keep only
  // the edges that land on the survivors: a graph with seventy leaves is a
  // texture, not a diagram
  const byIndicator = new Map<IndicatorId, number>()
  for (const edge of totals.values()) {
    byIndicator.set(edge.indicator, (byIndicator.get(edge.indicator) ?? 0) + Math.abs(edge.sigma))
  }
  const kept = new Set(
    [...byIndicator.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([id]) => id),
  )

  const edges = [...totals.values()]
    .filter((e) => kept.has(e.indicator))
    .sort((a, b) => Math.abs(b.sigma) - Math.abs(a.sigma))

  const order = (id: IndicatorId) => -(byIndicator.get(id) ?? 0)
  return {
    edges,
    specs: INTERVENTION_ORDER.filter((s) => edges.some((e) => e.spec === s)),
    systems: [...new Set(edges.map((e) => e.system))],
    indicators: [...kept].sort((a, b) => order(a) - order(b)),
    peak: edges.reduce((m, e) => Math.max(m, Math.abs(e.sigma)), 0.1),
  }
}

/* ------------------------------------------------------------------ risks */

export type RiskLevel = 'watch' | 'alert'

export interface Risk {
  indicator: IndicatorId
  level: RiskLevel
  /** which bound is being approached */
  side: 'low' | 'high'
  value: number
  confidence: Confidence
}

/**
 * Vitals leaving their reference interval, or close enough to be worth saying.
 *
 * "Approaching" is the useful signal: by the time a branch is stopped there is
 * nothing left to decide, and the point of watching a simulation run is to see
 * the problem arriving.
 */
export function branchRisks(
  scenario: Scenario,
  subject: Subject,
  baselines: Baselines,
  week: number,
  limit = 3,
): Risk[] {
  if (isControl(scenario)) return []
  const out: Risk[] = []

  for (const vital of VITALS) {
    const range = referenceFor(subject, vital.id)
    if (!range) continue
    // the same value the stop rule reads, so a risk that is about to end the
    // branch and the marker that ends it cannot disagree
    const value =
      simulate(scenario, vital.id, baselines).points[Math.round(week * 2)].value +
      adverseAt(scenario, vital.id, week)
    const start = baselines[vital.id]
    const span = range[1] - range[0]
    const margin = span * 0.12

    // a vital the subject was already outside of at week 0 is a chronic finding,
    // not something this protocol did; it only counts once it moves further out
    const startedHigh = start > range[1]
    const startedLow = start < range[0]

    if (value > range[1] && !startedHigh) {
      out.push({ indicator: vital.id, level: 'alert', side: 'high', value, confidence: 'medium' })
    } else if (value < range[0] && !startedLow) {
      out.push({ indicator: vital.id, level: 'alert', side: 'low', value, confidence: 'medium' })
    } else if (value <= range[1] && value > range[1] - margin && !startedHigh) {
      out.push({ indicator: vital.id, level: 'watch', side: 'high', value, confidence: 'medium' })
    } else if (value >= range[0] && value < range[0] + margin && !startedLow) {
      out.push({ indicator: vital.id, level: 'watch', side: 'low', value, confidence: 'medium' })
    }
  }

  return out.sort((a, b) => (a.level === b.level ? 0 : a.level === 'alert' ? -1 : 1)).slice(0, limit)
}
