import { INDICATOR_BY_ID, type IndicatorId } from './indicators'
import {
  HORIZON_WEEKS,
  INTERVENTIONS,
  branchNoiseSeries,
  chainProtocol,
  noiseSeries,
  type AppliedIntervention,
  type InterventionId,
} from './model'
import { referenceFor, type Baselines, type Subject, SNAPSHOT_PANEL } from './subject'
import {
  branchSenescenceWeek,
  SENESCENCE_STOP,
} from './mortality'

/**
 * The cohort of futures.
 *
 * One protocol is not one outcome. The same dose lands on a person who sleeps
 * six hours and on the same person sleeping eight, and those are different
 * trajectories — so the unit of simulation here is not the protocol, it is the
 * protocol crossed with every way the next nine months could actually go.
 *
 * Branches enumerate lifestyle context only (sleep, movement, diet, stress).
 * Protocol drugs shift every branch equally — they do not multiply the fan.
 */

export const WEEKS = HORIZON_WEEKS + 1

/** Above this the grid is sampled rather than enumerated, to stay interactive. */
export const MAX_BRANCHES = 6000

export type FactorId = 'sleep' | 'movement' | 'diet' | 'stress'

export interface FactorSpec {
  id: FactorId
  /** level values from -1 (worst) to +1 (best) */
  levels: number[]
  /** shift at level +1, in each analyte's own unit */
  effects: Partial<Record<IndicatorId, number>>
}

export const FACTORS: FactorSpec[] = [
  {
    id: 'sleep',
    levels: [-1, -0.34, 0.34, 1],
    effects: {
      sleep: 1.3,
      cortisol: -2.4,
      hrv: 7.5,
      restinghr: -4,
      crp: -0.5,
      il6: -0.32,
      glucose: -3.6,
      insulin: -1.7,
      homair: -0.36,
      testosterone: 46,
      leptin: -1.4,
      sbp: -3.5,
    },
  },
  {
    id: 'movement',
    levels: [-1, -0.34, 0.34, 1],
    effects: {
      activity: 3300,
      vo2max: 3.4,
      hdl: 5.2,
      trig: -23,
      homair: -0.5,
      glucose: -4.2,
      insulin: -2.1,
      weight: -2.4,
      bodyfat: -2.5,
      waist: -3.4,
      restinghr: -5.5,
      hrv: 6.5,
      sbp: -5.5,
      dbp: -3.2,
      crp: -0.42,
      igf1: 12,
    },
  },
  {
    id: 'diet',
    levels: [-1, -0.34, 0.34, 1],
    effects: {
      weight: -3.4,
      bmi: -1.1,
      bodyfat: -2.9,
      waist: -4.2,
      ldl: -19,
      chol: -22,
      apob: -13,
      nonhdl: -21,
      trig: -31,
      glucose: -5.2,
      hba1c: -0.23,
      homair: -0.46,
      crp: -0.6,
      urate: -0.52,
      alt: -5.5,
      ggt: -5,
    },
  },
  {
    id: 'stress',
    levels: [-1, 0, 1],
    effects: {
      cortisol: -3.4,
      crp: -0.4,
      il6: -0.26,
      sbp: -6.2,
      dbp: -4.1,
      hrv: 6.2,
      glucose: -2.6,
      sleep: 0.5,
      prolactin: -1.2,
    },
  },
]

/** When each lifestyle axis starts influencing the trajectory (matches fan forks). */
const LIFESTYLE_ONSET = [0, 4, 10, 18] as const
const LIFESTYLE_TAU = 8
/** Shared lab drift vs branch-specific biological variation. */
const PERSON_NOISE_SHARE = 0.28

function branchKeyFromDigits(digits: number[]): number {
  let key = 0
  for (let i = 0; i < digits.length; i += 1) key = key * 7 + digits[i] + 1
  return key
}

function lifestyleContribution(digits: number[], indicatorId: IndicatorId, week: number): number {
  let total = 0
  for (let f = 0; f < FACTORS.length; f += 1) {
    const onset = LIFESTYLE_ONSET[f]
    if (week < onset) continue
    const effect = FACTORS[f].effects[indicatorId]
    if (effect === undefined) continue
    const level = FACTORS[f].levels[digits[f]]
    const framp = 1 - Math.exp(-(week - onset) / LIFESTYLE_TAU)
    total += effect * level * framp
  }
  return total
}

/** Adherence levels an intervention can be taken at. */
export const ADHERENCE_LEVELS = [0.35, 0.7, 1]

/**
 * Analytes that can stop a branch, with how heavily each one counts.
 *
 * These are the ones where drifting far outside the reference interval is not a
 * worse number but a different clinical situation.
 */
export const VITALS: { id: IndicatorId; weight: number }[] = [
  { id: 'ft4', weight: 1.3 },
  { id: 'ft3', weight: 1.0 },
  { id: 'calcium', weight: 1.4 },
  { id: 'glucose', weight: 1.0 },
  { id: 'sbp', weight: 1.1 },
  // a tight reference and a small sigma make resting heart rate the most
  // trigger-happy row in the panel; it counts, but it should not decide alone
  { id: 'restinghr', weight: 0.35 },
  { id: 'hgb', weight: 1.0 },
  { id: 'egfr', weight: 1.0 },
  { id: 'alt', weight: 0.7 },
  { id: 'crp', weight: 0.6 },
]

/** The panel the improvement score is read from. All have reference intervals. */
export const SCORE_PANEL: IndicatorId[] = [
  'glucose',
  'hba1c',
  'homair',
  'ldl',
  'hdl',
  'trig',
  'crp',
  'vitd',
  'sbp',
  'dbp',
  'bmi',
  'alt',
  'tsh',
]

/** Cumulative hazard at which a branch is stopped. */
const CRITICAL_HAZARD = 12

/**
 * How much worse than the starting point a vital has to get, in its own sigma,
 * before it counts against the branch at all.
 */
const CRITICAL_SLACK = 1.6

/**
 * Hazard carried from one week to the next.
 *
 * Without it a single bad week ends a branch. What should end one is a load the
 * body does not get out from under, so the accumulator forgets slowly and a
 * transient excursion is survivable.
 */
const HAZARD_CARRY = 0.92

export type Outcome = 'improved' | 'flat' | 'worsened' | 'stopped'

/** How much the composite has to move before a branch counts as changed. */
const OUTCOME_BAND = 0.1

export interface RunConfig {
  subject: Subject
  baselines: Baselines
  protocol: AppliedIntervention[]
}

export interface WeekStats {
  active: number
  stopped: number
  improved: number
  flat: number
  worsened: number
  p05: number
  p50: number
  p95: number
}

export const PANEL_SIZE = SNAPSHOT_PANEL.length

export interface RunResult {
  count: number
  /** display indicator, [branch * WEEKS + week] */
  paths: Float32Array
  /** snapshot panel per branch/week, [branch * WEEKS * PANEL_SIZE + week * PANEL_SIZE + panel] */
  panelPaths: Float32Array
  /** composite burden, lower is healthier, [branch * WEEKS + week] */
  scores: Float32Array
  /** week a branch was stopped, or -1 if it reached the horizon */
  stopWeek: Int16Array
  /** index into VITALS of what stopped it */
  stopReason: Int8Array
  /** chosen level index per factor, [branch * FACTORS.length + factor] */
  levels: Uint8Array
  domain: [number, number]
  baselineScore: number
  stats: WeekStats[]
  adherenceAxes: InterventionId[]
  /** grid size before sampling */
  gridSize: number
  elapsedMs: number
}

/** Snapshot-panel value for one branch at one week. */
export function branchPanelValue(
  result: RunResult,
  branch: number,
  week: number,
  panelIndex: number,
): number {
  return result.panelPaths[branch * WEEKS * PANEL_SIZE + week * PANEL_SIZE + panelIndex]
}

export function branchPanelIndex(id: IndicatorId): number {
  return SNAPSHOT_PANEL.indexOf(id)
}

/** Total lifestyle branches the grid enumerates (protocol does not change this). */
export function gridSizeOf(_protocol: AppliedIntervention[]): number {
  return FACTORS.reduce((n, f) => n * f.levels.length, 1)
}

/** Distance outside a reference interval, in the analyte's own sigma. */
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

export function runCohort({ subject, baselines, protocol }: RunConfig): RunResult {
  const t0 = performance.now()

  const active = chainProtocol(protocol)
  const drugs = [...new Set(active.map((iv) => iv.spec))]

  const response = active.map((iv) => {
    const tau = INTERVENTIONS[iv.spec].tau
    const end = iv.endWeek ?? Infinity
    const out = new Float64Array(WEEKS)
    for (let w = 0; w < WEEKS; w += 1) {
      if (w <= iv.startWeek) continue
      const built = 1 - Math.exp(-(Math.min(w, end) - iv.startWeek) / tau)
      out[w] = w <= end ? built : built * Math.exp(-(w - end) / tau)
    }
    return out
  })

  // ------------------------------------------------------------ tracked panel
  const tracked = [...new Set<IndicatorId>([...SNAPSHOT_PANEL, ...VITALS.map((v) => v.id), ...SCORE_PANEL])]
  const trackedIndex = new Map(tracked.map((id, i) => [id, i]))
  /** Legacy paths column — glucose, used for domain metadata only. */
  const pathsSlot = trackedIndex.get('glucose') as number

  const personNoise = tracked.map((id) => noiseSeries(id))
  const base = tracked.map((id) => baselines[id])
  const sigma = tracked.map((id) => INDICATOR_BY_ID[id].sigma)
  const ranges = tracked.map((id) => referenceFor(subject, id))

  const vitalSlots = VITALS.map((v) => trackedIndex.get(v.id) as number)
  const scoreSlots = SCORE_PANEL.map((id) => trackedIndex.get(id) as number)
  const panelSlots = SNAPSHOT_PANEL.map((id) => trackedIndex.get(id) as number)

  // The stop rule is about deterioration, not about being unwell. Someone whose
  // CRP is already at 4 mg/L has a chronic problem, not an emergency, and a
  // threshold read off the reference interval alone would end every branch of
  // his run in the third week. So the ceiling is anchored on whichever is worse,
  // the reference bound or where this subject actually starts.
  const critHi = tracked.map((_, s) =>
    ranges[s] ? Math.max(ranges[s]![1], base[s]) + CRITICAL_SLACK * sigma[s] : Infinity,
  )
  const critLo = tracked.map((_, s) =>
    ranges[s] ? Math.min(ranges[s]![0], base[s]) - CRITICAL_SLACK * sigma[s] : -Infinity,
  )

  // baseline burden: the subject's starting distance from healthy
  let baselineScore = 0
  for (let s = 0; s < scoreSlots.length; s += 1) {
    const slot = scoreSlots[s]
    baselineScore += excursion(base[slot], ranges[slot], sigma[slot])
  }
  baselineScore /= scoreSlots.length

  // -------------------------------------------------------------- the grid
  const dims = FACTORS.map((f) => f.levels.length)
  const gridSize = dims.reduce((n, d) => n * d, 1)
  const count = Math.min(gridSize, MAX_BRANCHES)
  // a plain stride would lock the fastest-moving axis to one value, so the grid
  // is walked by a step coprime with its size and stays evenly covered
  const step = gridSize <= MAX_BRANCHES ? 1 : coprimeStride(gridSize)

  const paths = new Float32Array(count * WEEKS)
  const panelPaths = new Float32Array(count * WEEKS * PANEL_SIZE)
  const scores = new Float32Array(count * WEEKS)
  const stopWeek = new Int16Array(count).fill(-1)
  const stopReason = new Int8Array(count).fill(-1)
  // the level index, not its value: a breakdown that groups by float equality
  // silently loses every level whose value is not exact in binary
  const levels = new Uint8Array(count * FACTORS.length)

  const gain = active.map(() => new Float64Array(tracked.length))
  const digits = new Array(dims.length).fill(0)

  let domainLo = Infinity
  let domainHi = -Infinity

  for (let b = 0; b < count; b += 1) {
    decode((b * step) % gridSize, dims, digits)

    // ---------------------------------------------------- this branch's world
    let badness = 0
    for (let f = 0; f < FACTORS.length; f += 1) {
      const level = FACTORS[f].levels[digits[f]]
      levels[b * FACTORS.length + f] = digits[f]
      badness += (1 - level) / 2
    }
    badness /= FACTORS.length

    const branchKey = branchKeyFromDigits(digits)
    const senescenceWeek = branchSenescenceWeek(subject, branchKey, badness)
    const branchNoise = tracked.map((id) => branchNoiseSeries(id, branchKey))

    for (let g = 0; g < gain.length; g += 1) gain[g].fill(0)
    for (let a = 0; a < active.length; a += 1) {
      const iv = active[a]
      const meta = INTERVENTIONS[iv.spec]
      const doseFrac = iv.dose / meta.refDose
      const adverseScale = Math.pow(iv.dose / meta.max, 2) * (1 + 1.2 * badness)
      for (const key of Object.keys(meta.effects) as IndicatorId[]) {
        const slot = trackedIndex.get(key)
        if (slot === undefined) continue
        gain[a][slot] += (meta.effects[key] as number) * doseFrac
      }
      if (meta.adverse) {
        for (const key of Object.keys(meta.adverse) as IndicatorId[]) {
          const slot = trackedIndex.get(key)
          if (slot === undefined) continue
          gain[a][slot] += (meta.adverse[key] as number) * adverseScale
        }
      }
    }

    // ------------------------------------------------------------- the weeks
    let hazard = 0
    for (let w = 0; w < WEEKS; w += 1) {
      let burden = 0
      let worstVital = -1
      let worstExc = 0
      let weekHazard = 0

      for (let s = 0; s < tracked.length; s += 1) {
        const id = tracked[s]
        const lifestyle = lifestyleContribution(digits, id, w)
        let value =
          base[s] +
          personNoise[s][w] * PERSON_NOISE_SHARE +
          branchNoise[s][w] * (1 - PERSON_NOISE_SHARE) +
          lifestyle
        for (let a = 0; a < active.length; a += 1) value += gain[a][s] * response[a][w]
        if (value < 0) value = 0
        if (s === pathsSlot) {
          paths[b * WEEKS + w] = value
          if (value < domainLo) domainLo = value
          if (value > domainHi) domainHi = value
        }
        for (let p = 0; p < PANEL_SIZE; p += 1) {
          if (panelSlots[p] === s) {
            panelPaths[b * WEEKS * PANEL_SIZE + w * PANEL_SIZE + p] = value
          }
        }
        // reused across both readouts: burden measures ordinary drift, hazard
        // only counts the part that is far enough out to be a different problem
        driftScratch[s] = excursion(value, ranges[s], sigma[s])
        farScratch[s] =
          value > critHi[s]
            ? (value - critHi[s]) / sigma[s]
            : value < critLo[s]
              ? (critLo[s] - value) / sigma[s]
              : 0
      }

      for (let i = 0; i < scoreSlots.length; i += 1) burden += driftScratch[scoreSlots[i]]
      burden /= scoreSlots.length
      scores[b * WEEKS + w] = burden

      for (let i = 0; i < vitalSlots.length; i += 1) {
        const exc = farScratch[vitalSlots[i]]
        if (exc <= 0) continue
        weekHazard += VITALS[i].weight * exc * exc
        if (exc > worstExc) {
          worstExc = exc
          worstVital = i
        }
      }

      hazard = hazard * HAZARD_CARRY + weekHazard
      if (hazard > CRITICAL_HAZARD) {
        stopWeek[b] = w
        stopReason[b] = worstVital
        // the branch has no further future: hold its last value so the plot can
        // draw it as a line that ends rather than one that vanishes
        for (let rest = w + 1; rest < WEEKS; rest += 1) {
          paths[b * WEEKS + rest] = paths[b * WEEKS + w]
          scores[b * WEEKS + rest] = burden
        }
        break
      }

      if (senescenceWeek < HORIZON_WEEKS && w >= senescenceWeek) {
        stopWeek[b] = w
        stopReason[b] = SENESCENCE_STOP
        for (let rest = w + 1; rest < WEEKS; rest += 1) {
          paths[b * WEEKS + rest] = paths[b * WEEKS + w]
          scores[b * WEEKS + rest] = burden
        }
        break
      }
    }
  }

  const stats = weekStats({ count, scores, stopWeek, paths, baselineScore })

  const pad = (domainHi - domainLo) * 0.06 || 1
  return {
    count,
    paths,
    panelPaths,
    scores,
    stopWeek,
    stopReason,
    levels,
    domain: [Math.max(0, domainLo - pad), domainHi + pad],
    baselineScore,
    stats,
    adherenceAxes: drugs,
    gridSize,
    elapsedMs: performance.now() - t0,
  }
}

// scratch buffers, sized once for the largest tracked panel
const driftScratch = new Float64Array(64)
const farScratch = new Float64Array(64)

/** Positions of a flat index in a mixed-radix grid, written into `out`. */
function decode(index: number, dims: number[], out: number[]): void {
  let rest = index
  for (let d = dims.length - 1; d >= 0; d -= 1) {
    out[d] = rest % dims[d]
    rest = Math.floor(rest / dims[d])
  }
}

/** A stride that visits the whole grid before repeating. */
function coprimeStride(size: number): number {
  const candidates = [4099, 3571, 2729, 1741, 997, 613, 271]
  for (const c of candidates) if (gcd(c, size) === 1) return c
  return 1
}

function gcd(a: number, b: number): number {
  while (b) [a, b] = [b, a % b]
  return a
}

interface StatsInput {
  count: number
  scores: Float32Array
  stopWeek: Int16Array
  paths: Float32Array
  baselineScore: number
}

/**
 * Per-week tallies, computed once so playback is a lookup.
 *
 * The counters have to move while the run plays — a branch that will be stopped
 * at week 22 is still active at week 21 — so every week gets its own census.
 */
function weekStats({ count, scores, stopWeek, paths, baselineScore }: StatsInput): WeekStats[] {
  const out: WeekStats[] = []
  const column = new Float64Array(count)

  for (let w = 0; w < WEEKS; w += 1) {
    let stopped = 0
    let improved = 0
    let worsened = 0
    let flat = 0
    let live = 0

    for (let b = 0; b < count; b += 1) {
      const stop = stopWeek[b]
      if (stop >= 0 && stop <= w) {
        stopped += 1
        continue
      }
      const gainOnBaseline = baselineScore - scores[b * WEEKS + w]
      if (gainOnBaseline > OUTCOME_BAND) improved += 1
      else if (gainOnBaseline < -OUTCOME_BAND) worsened += 1
      else flat += 1
      column[live] = paths[b * WEEKS + w]
      live += 1
    }

    // slice, not from: the iterator protocol costs more than the memcpy for
    // several thousand branches repeated across every week of the horizon
    const sorted = column.slice(0, Math.max(1, live)).sort()
    out.push({
      active: live,
      stopped,
      improved,
      flat,
      worsened,
      p05: sorted[Math.floor(sorted.length * 0.05)],
      p50: sorted[Math.floor(sorted.length * 0.5)],
      p95: sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))],
    })
  }
  return out
}

/** Per-week percentiles for any snapshot-panel indicator — no cohort rerun needed. */
export function weekStatsForIndicator(result: RunResult, indicatorId: IndicatorId): WeekStats[] {
  const pi = branchPanelIndex(indicatorId)
  if (pi < 0) return result.stats

  const out: WeekStats[] = []
  const column = new Float64Array(result.count)

  for (let w = 0; w < WEEKS; w += 1) {
    let stopped = 0
    let improved = 0
    let worsened = 0
    let flat = 0
    let live = 0

    for (let b = 0; b < result.count; b += 1) {
      const stop = result.stopWeek[b]
      if (stop >= 0 && stop <= w) {
        stopped += 1
        continue
      }
      const gainOnBaseline = result.baselineScore - result.scores[b * WEEKS + w]
      if (gainOnBaseline > OUTCOME_BAND) improved += 1
      else if (gainOnBaseline < -OUTCOME_BAND) worsened += 1
      else flat += 1
      column[live] = branchPanelValue(result, b, w, pi)
      live += 1
    }

    const sorted = column.slice(0, Math.max(1, live)).sort()
    out.push({
      active: live,
      stopped,
      improved,
      flat,
      worsened,
      p05: sorted[Math.floor(sorted.length * 0.05)],
      p50: sorted[Math.floor(sorted.length * 0.5)],
      p95: sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))],
    })
  }
  return out
}

export interface FactorBreakdown {
  factor: FactorSpec
  rows: { level: number; improvement: number; stoppedShare: number }[]
}

/**
 * What each way of living was worth, averaged over everything else.
 *
 * This is the readout the cohort exists for: it separates "the protocol works"
 * from "the protocol works if he also sleeps", which a single trajectory cannot.
 */
export function factorBreakdown(result: RunResult): FactorBreakdown[] {
  return FACTORS.map((factor, f) => {
    const rows = factor.levels.map((level, index) => {
      let sum = 0
      let n = 0
      let stopped = 0
      for (let b = 0; b < result.count; b += 1) {
        if (result.levels[b * FACTORS.length + f] !== index) continue
        n += 1
        if (result.stopWeek[b] >= 0) {
          stopped += 1
          continue
        }
        sum += result.baselineScore - result.scores[b * WEEKS + HORIZON_WEEKS]
      }
      const survivors = n - stopped
      return {
        level,
        improvement: survivors > 0 ? sum / survivors : 0,
        stoppedShare: n > 0 ? stopped / n : 0,
      }
    })
    return { factor, rows }
  })
}

/** How many branches each stop reason accounted for, largest first. */
export function stopReasons(
  result: RunResult,
): { id: IndicatorId | 'senescence'; count: number }[] {
  const tally = new Map<number, number>()
  for (let b = 0; b < result.count; b += 1) {
    const r = result.stopReason[b]
    if (r < 0) continue
    tally.set(r, (tally.get(r) ?? 0) + 1)
  }
  const out: { id: IndicatorId | 'senescence'; count: number }[] = [...tally.entries()]
    .filter(([index]) => index !== SENESCENCE_STOP)
    .sort((a, b) => b[1] - a[1])
    .map(([index, count]) => ({ id: VITALS[index].id, count }))
  const ageCount = tally.get(SENESCENCE_STOP)
  if (ageCount) out.push({ id: 'senescence', count: ageCount })
  return out.sort((a, b) => b.count - a.count)
}
