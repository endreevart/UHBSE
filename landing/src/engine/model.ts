import { INDICATORS, INDICATOR_BY_ID, type Indicator, type IndicatorId } from './indicators'

export * from './indicators'

export const HORIZON_WEEKS = 560

/** Yearly readouts across the simulation horizon, plus the final week. */
export const CHECKPOINTS = [
  ...Array.from({ length: Math.floor(HORIZON_WEEKS / 52) }, (_, i) => (i + 1) * 52),
  HORIZON_WEEKS,
].filter((week, index, list) => list.indexOf(week) === index)

export type InterventionId = 'vitaminD' | 'levothyroxine' | 'nutrition' | 'activity'

/**
 * Where an effect estimate came from. The engine keeps these apart on purpose:
 * an effect read out of the clinic's own records, one entered from a guideline,
 * and one invented for a demonstration are not the same claim, and a system that
 * lets them blur into each other cannot be audited later.
 */
export type EffectOrigin = 'DERIVED' | 'ANNOTATED' | 'SYNTHETIC'

/** Evidence status of the mapping, independent of where the number came from. */
export type EffectStatus = 'CONFIRMED' | 'LIKELY' | 'UNKNOWN'

export interface Provenance {
  origin: EffectOrigin
  status: EffectStatus
  /** short human-readable source label */
  source: string
  /** relative half-width of the effect interval, e.g. 0.4 means ±40% */
  spread: number
}

export interface InterventionSpec {
  id: InterventionId
  min: number
  max: number
  step: number
  /** dose at which `effects` are reached in full */
  refDose: number
  defaultDose: number
  /** weeks until ~63% of the effect is expressed */
  tau: number
  effects: Partial<Record<IndicatorId, number>>
  /**
   * Off-target load at the maximum dose.
   *
   * Kept apart from `effects` because it does not behave like them: it grows
   * with the square of the dose and is amplified when the person is sleeping
   * badly, not moving and eating poorly. This is what makes an aggressive
   * protocol in a bad context a different proposition from the same protocol in
   * a good one, rather than simply a stronger version of it.
   */
  adverse?: Partial<Record<IndicatorId, number>>
  provenance: Provenance
}

/**
 * Effects are the full change in each analyte's own unit at `refDose`. They are
 * deliberately pleiotropic: no protocol touches one system alone, and the whole
 * point of the panel view is that this is visible rather than asserted.
 */
export const INTERVENTIONS: Record<InterventionId, InterventionSpec> = {
  vitaminD: {
    id: 'vitaminD',
    min: 0,
    max: 6000,
    step: 500,
    refDose: 2000,
    defaultDose: 2000,
    tau: 10,
    // every effect on this page is invented for the demonstration; the slot is
    // here so the question "where did this number come from" has somewhere to
    // be answered once real estimates replace them
    provenance: { origin: 'SYNTHETIC', status: 'UNKNOWN', source: 'demo', spread: 0.35 },
    // at 6000 IU the limiting problem is calcium, not vitamin D
    adverse: { calcium: 0.9, urate: 0.5, egfr: -7, crp: 0.2 },
    effects: {
      vitd: 17.5,
      pth: -9,
      calcium: 0.08,
      magnesium: 0.03,
      alp: -4,
      glucose: -1.2,
      hba1c: -0.06,
      insulin: -1.1,
      homair: -0.28,
      crp: -0.35,
      il6: -0.15,
      testosterone: 18,
      sleep: 0.12,
    },
  },
  levothyroxine: {
    id: 'levothyroxine',
    min: 0,
    max: 125,
    step: 12.5,
    refDose: 50,
    defaultDose: 50,
    tau: 6,
    provenance: { origin: 'SYNTHETIC', status: 'UNKNOWN', source: 'demo', spread: 0.3 },
    // over-replacement: the thyroid axis overshoots and the heart follows
    adverse: { ft4: 0.72, ft3: 1.5, restinghr: 16, sbp: 14, hrv: -16, alt: 8 },
    effects: {
      tsh: -1.05,
      ft4: 0.32,
      ft3: 0.35,
      rt3: 0.04,
      weight: -1.1,
      bmi: -0.36,
      bodyfat: -0.7,
      glucose: 0.8,
      chol: -14,
      ldl: -11,
      nonhdl: -12,
      apob: -8,
      restinghr: 3.5,
      hrv: -2.5,
      vo2max: 1.2,
      shbg: 6,
      prolactin: -2,
      creatinine: -0.04,
      egfr: 3,
      homocysteine: -1.1,
      crp: -0.2,
    },
  },
  nutrition: {
    id: 'nutrition',
    min: 0,
    max: 900,
    step: 50,
    refDose: 500,
    defaultDose: 400,
    tau: 14,
    provenance: { origin: 'SYNTHETIC', status: 'UNKNOWN', source: 'demo', spread: 0.45 },
    // a deep deficit stops being weight loss and becomes catabolism
    adverse: { hgb: -1.2, albumin: -0.45, leanmass: -4.2, testosterone: -130, restinghr: -9, hrv: -6 },
    effects: {
      weight: -5.4,
      bmi: -1.75,
      waist: -5.5,
      bodyfat: -2.6,
      leanmass: -0.9,
      glucose: -6.2,
      hba1c: -0.3,
      insulin: -4.2,
      homair: -1.2,
      cpeptide: -0.5,
      fructosamine: -18,
      chol: -18,
      ldl: -12,
      hdl: 3,
      trig: -38,
      apob: -11,
      nonhdl: -16,
      alt: -7,
      ast: -4,
      ggt: -9,
      crp: -0.9,
      il6: -0.5,
      fibrinogen: -0.3,
      ferritin: -14,
      urate: -0.5,
      egfr: 2,
      sbp: -6,
      dbp: -4,
      leptin: -6.5,
      igf1: -12,
      vitd: 1.5,
      albumin: -0.08,
      b12: -18,
      folate: 1.2,
    },
  },
  activity: {
    id: 'activity',
    min: 0,
    max: 9000,
    step: 500,
    refDose: 4000,
    defaultDose: 3500,
    tau: 8,
    provenance: { origin: 'SYNTHETIC', status: 'UNKNOWN', source: 'demo', spread: 0.5 },
    // load without recovery reads as inflammation, not fitness
    adverse: { crp: 1.3, alt: 13, restinghr: 7, hrv: -9, cortisol: 2.4 },
    effects: {
      activity: 4000,
      vo2max: 3.4,
      restinghr: -5.5,
      hrv: 9,
      weight: -2.1,
      bmi: -0.68,
      waist: -2.4,
      bodyfat: -1.5,
      leanmass: 0.6,
      glucose: -3.8,
      hba1c: -0.18,
      insulin: -2.4,
      homair: -0.7,
      hdl: 5.5,
      trig: -22,
      ldl: -4,
      nonhdl: -6,
      crp: -0.4,
      il6: -0.3,
      sbp: -4.5,
      dbp: -3,
      ft3: 0.03,
      testosterone: 25,
      igf1: 9,
      cortisol: -0.8,
      leptin: -2.2,
      sleep: 0.3,
      hgb: 0.15,
      ferritin: -8,
      homocysteine: -0.6,
      urate: -0.2,
    },
  },
}

export const INTERVENTION_ORDER: InterventionId[] = [
  'levothyroxine',
  'vitaminD',
  'nutrition',
  'activity',
]

/** Explicit protocol items the user adds. Lifestyle axes are randomized per branch in the cohort engine. */
export const USER_PROTOCOL_SPECS: InterventionId[] = ['levothyroxine', 'vitaminD']

export interface AppliedIntervention {
  key: string
  spec: InterventionId
  dose: number
  startWeek: number
  /** week at which this dose segment is replaced; the effect then washes out */
  endWeek?: number
}

export interface Scenario {
  id: string
  colorIndex: number
  /** week at which this scenario separated from its parent, 0 for the root */
  branchWeek: number
  parentId: string | null
  interventions: AppliedIntervention[]
}

/** Deterministic band-limited noise so every render of a scenario looks identical. */
function wobble(seed: number, t: number): number {
  return (
    Math.sin(t * 0.62 + seed * 1.7) * 0.5 +
    Math.sin(t * 1.47 + seed * 3.1) * 0.31 +
    Math.sin(t * 2.93 + seed * 5.3) * 0.19
  )
}

function seedOf(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 997) / 997
}

/**
 * Fraction of an intervention's full effect expressed at week `t`:
 * exponential build-up from `startWeek`, exponential wash-out after `endWeek`.
 */
function response(t: number, startWeek: number, endWeek: number | undefined, tau: number): number {
  if (t <= startWeek) return 0
  if (endWeek === undefined || t <= endWeek) return 1 - Math.exp(-(t - startWeek) / tau)
  const atEnd = 1 - Math.exp(-(endWeek - startWeek) / tau)
  return atEnd * Math.exp(-(t - endWeek) / tau)
}

/**
 * Weekly measurement noise for one indicator.
 *
 * Shared component: lab drift common to every branch of one subject run.
 * Branch-specific wobble is mixed in inside the cohort engine.
 */
export function noiseSeries(indicatorId: IndicatorId): Float64Array {
  const indicator = INDICATOR_BY_ID[indicatorId]
  const seed = seedOf(indicatorId)
  const out = new Float64Array(HORIZON_WEEKS + 1)
  for (let w = 0; w <= HORIZON_WEEKS; w += 1) out[w] = wobble(seed, w) * indicator.noise
  return out
}

/** Per-branch noise — lifestyle futures diverge in shape, not only in level. */
export function branchNoiseSeries(indicatorId: IndicatorId, branchKey: number): Float64Array {
  const indicator = INDICATOR_BY_ID[indicatorId]
  const seed = seedOf(`${indicatorId}:branch:${branchKey}`)
  const phase = branchKey * 0.173
  const out = new Float64Array(HORIZON_WEEKS + 1)
  for (let w = 0; w <= HORIZON_WEEKS; w += 1) {
    out[w] = wobble(seed, w + phase) * indicator.noise
  }
  return out
}

/**
 * Chain the dose segments of each intervention.
 *
 * A titration step is not a second course of the drug on top of the first: the
 * previous dose stops where the new one starts. Closing each segment at the next
 * one's start week makes a switch behave the way it should — the old dose washes
 * out while the new one builds up — and it means the editor only ever has to
 * store a dose and a start week.
 */
export function chainSegments(scenario: Scenario): Scenario {
  const bySpec = new Map<InterventionId, AppliedIntervention[]>()
  for (const iv of scenario.interventions) {
    const list = bySpec.get(iv.spec)
    if (list) list.push(iv)
    else bySpec.set(iv.spec, [iv])
  }

  const interventions: AppliedIntervention[] = []
  for (const list of bySpec.values()) {
    const sorted = [...list].sort((a, b) => a.startWeek - b.startWeek)
    sorted.forEach((iv, i) => {
      const next = sorted[i + 1]
      interventions.push({ ...iv, endWeek: next ? next.startWeek : undefined })
    })
  }
  return { ...scenario, interventions }
}

/** Close dose segments per drug so each start week hands off to the next. */
export function chainProtocol(protocol: AppliedIntervention[]): AppliedIntervention[] {
  const active = protocol.filter((iv) => iv.dose > 0)
  const bySpec = new Map<InterventionId, AppliedIntervention[]>()
  for (const iv of active) {
    const list = bySpec.get(iv.spec) ?? []
    list.push(iv)
    bySpec.set(iv.spec, list)
  }

  const out: AppliedIntervention[] = []
  for (const list of bySpec.values()) {
    const sorted = [...list].sort((a, b) => a.startWeek - b.startWeek)
    sorted.forEach((iv, i) => {
      const next = sorted[i + 1]
      const endWeek = iv.endWeek ?? (next ? next.startWeek : undefined)
      out.push({ ...iv, endWeek })
    })
  }
  return out.sort((a, b) => a.startWeek - b.startWeek)
}

export interface Point {
  t: number
  value: number
  lower: number
  upper: number
  innerLower: number
  innerUpper: number
}

export interface Series {
  indicator: IndicatorId
  points: Point[]
  /** value at each checkpoint week */
  checkpoints: { t: number; value: number; lower: number; upper: number }[]
}

/**
 * `baselines` is the subject's starting point. Without it the catalogue value is
 * used, which describes nobody in particular — the same protocol on a 52-year-old
 * with a BMI of 29 and on a lean 30-year-old has to start from different numbers
 * or the whole exercise is decorative.
 */
export function simulate(
  scenario: Scenario,
  indicatorId: IndicatorId,
  baselines?: Partial<Record<IndicatorId, number>>,
): Series {
  const indicator = INDICATOR_BY_ID[indicatorId]
  const baseline = baselines?.[indicatorId] ?? indicator.baseline
  // measurement noise belongs to the person, not to the scenario, so branches
  // stay pixel-identical until they actually diverge
  const seed = seedOf(indicatorId)
  const active = scenario.interventions.filter((iv) => iv.dose > 0)

  const points: Point[] = []
  for (let t = 0; t <= HORIZON_WEEKS; t += 0.5) {
    let value = baseline
    let load = 0

    for (const iv of active) {
      const spec = INTERVENTIONS[iv.spec]
      const effect = spec.effects[indicatorId]
      const r = response(t, iv.startWeek, iv.endWeek, spec.tau)
      if (effect) value += effect * (iv.dose / spec.refDose) * r
      load += r * (iv.dose / spec.refDose)
    }

    value += wobble(seed, t) * indicator.noise

    // uncertainty widens with the horizon and with how much has been changed
    const horizon = Math.sqrt(t / HORIZON_WEEKS)
    const sigma = indicator.sigma * (0.12 + 0.88 * horizon) * (1 + 0.35 * Math.min(load, 3))

    // these are concentrations, masses and counts: never negative
    const floor = 0
    points.push({
      t,
      value: Math.max(floor, value),
      // outer band is the 95% interval, inner is 68% — both labelled as such in the chart
      lower: Math.max(floor, value - 1.96 * sigma),
      upper: value + 1.96 * sigma,
      innerLower: Math.max(floor, value - sigma),
      innerUpper: value + sigma,
    })
  }

  const checkpoints = CHECKPOINTS.map((week) => {
    const p = points[Math.round(week * 2)]
    return { t: week, value: p.value, lower: p.lower, upper: p.upper }
  })

  return { indicator: indicatorId, points, checkpoints }
}

export function valueAt(scenario: Scenario, indicatorId: IndicatorId, week: number) {
  const series = simulate(scenario, indicatorId)
  const idx = Math.max(0, Math.min(series.points.length - 1, Math.round(week * 2)))
  return series.points[idx]
}

export function formatValue(indicatorId: IndicatorId, value: number): string {
  const indicator = INDICATOR_BY_ID[indicatorId]
  if (indicator.decimals === 0 && Math.abs(indicator.baseline) >= 1000) {
    return Math.round(value).toLocaleString('en-US')
  }
  return value.toFixed(indicator.decimals)
}

/** Phosphor-like arm colours; the control arm is deliberately colourless. */
export const SCENARIO_COLORS = [
  'var(--arm-1)',
  'var(--arm-2)',
  'var(--arm-3)',
  'var(--arm-4)',
  'var(--arm-5)',
]
export const CONTROL_COLOR = 'var(--arm-control)'

export const CONTROL_ID = 'control'

/**
 * The untreated arm. Every other arm is read against it, so it carries no
 * interventions and is never edited.
 */
export function createControlScenario(): Scenario {
  return { id: CONTROL_ID, colorIndex: -1, branchWeek: 0, parentId: null, interventions: [] }
}

export const isControl = (s: Scenario) => s.id === CONTROL_ID

/**
 * Protocols offered to a new arm, in order. Each one is deliberately different
 * from the last so a freshly created arm separates from the control immediately.
 */
export const ARM_PRESETS: { spec: InterventionId; dose: number }[][] = [
  // the opening arm is deliberately a combined protocol: a single-agent one
  // lights up three rows of the effect map and understates what the engine does.
  // Both agents are prescribed rather than behavioural, so the cohort's own
  // sleep, movement, diet and stress axes stay a separate question from the dose
  [
    { spec: 'vitaminD', dose: 4000 },
    { spec: 'levothyroxine', dose: 50 },
  ],
  [
    { spec: 'nutrition', dose: 500 },
    { spec: 'activity', dose: 4000 },
  ],
  [{ spec: 'levothyroxine', dose: 50 }],
  [
    { spec: 'levothyroxine', dose: 75 },
    { spec: 'vitaminD', dose: 2000 },
  ],
]

/** Difference between an arm and the untreated control at a given week. */
export function deltaVsControl(
  scenario: Scenario,
  control: Scenario,
  indicatorId: IndicatorId,
  week: number,
): number {
  return valueAt(scenario, indicatorId, week).value - valueAt(control, indicatorId, week).value
}

/**
 * An effect expressed in units of the indicator's own model sigma.
 *
 * Seventy analytes carry seventy incompatible units, so any view that puts them
 * on one scale has to be dimensionless. Sigma is the natural choice here: it is
 * what the simulation already knows about each indicator, and it makes "moved a
 * lot" mean the same thing for TSH and for daily steps.
 */
export interface EffectClaim {
  indicator: Indicator
  /** effect at the reference dose, in the indicator's own units */
  effect: number
  lo: number
  hi: number
  /** the same effect expressed in standard deviations */
  sigma: number
}

/**
 * What an intervention claims to do, largest first, as an interval rather than
 * a point. A single number would imply a precision none of these estimates have.
 */
export function effectClaims(specId: InterventionId, limit = 6): EffectClaim[] {
  const spec = INTERVENTIONS[specId]
  const { spread } = spec.provenance
  return (Object.keys(spec.effects) as IndicatorId[])
    .map((id) => {
      const effect = spec.effects[id] as number
      const indicator = INDICATOR_BY_ID[id]
      return {
        indicator,
        effect,
        lo: effect * (1 - spread),
        hi: effect * (1 + spread),
        sigma: effect / indicator.sigma,
      }
    })
    .sort((a, b) => Math.abs(b.sigma) - Math.abs(a.sigma))
    .slice(0, limit)
}

export function toSigma(indicatorId: IndicatorId, delta: number): number {
  return delta / INDICATOR_BY_ID[indicatorId].sigma
}

/** Colour ramp saturates here; beyond 3 sigma the difference stops being readable. */
export const SIGMA_CLAMP = 3

export interface EffectRow {
  indicator: Indicator
  /** effect in sigma at each whole week, 0..HORIZON_WEEKS */
  weekly: number[]
  /** largest absolute effect over the horizon, used for ranking */
  peak: number
}

/**
 * Effect of one arm against the control for every indicator, sampled weekly.
 * Weekly is deliberate: the heatmap cell is ~14px wide, and half-week resolution
 * would only add DOM nodes nobody can see.
 */
export function effectGrid(
  arm: Scenario,
  control: Scenario,
  baselines?: Partial<Record<IndicatorId, number>>,
): EffectRow[] {
  return INDICATORS.map((indicator) => {
    const armSeries = simulate(arm, indicator.id, baselines).points
    const ctrlSeries = simulate(control, indicator.id, baselines).points
    const weekly: number[] = []
    let peak = 0
    for (let week = 0; week <= HORIZON_WEEKS; week += 1) {
      const e = toSigma(indicator.id, armSeries[week * 2].value - ctrlSeries[week * 2].value)
      weekly.push(e)
      peak = Math.max(peak, Math.abs(e))
    }
    return { indicator, weekly, peak }
  })
}
