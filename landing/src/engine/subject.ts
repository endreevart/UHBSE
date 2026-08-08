import { INDICATORS, type IndicatorId } from './indicators'

/**
 * The person the simulation is about.
 *
 * Without one, every branch starts from the same catalogue baseline and the
 * engine is just an animation. Sex, age, body composition and history are what
 * make a protocol land differently on two people, so they are inputs to the
 * baseline rather than decoration in a panel.
 *
 * Every coefficient below is illustrative and invented for the demonstration —
 * the same synthetic status the interventions carry.
 */

export type Sex = 'male' | 'female'

export type HistoryId =
  | 'prediabetes'
  | 'hypothyroid'
  | 'vitdDeficiency'
  | 'dyslipidemia'
  | 'hypertension'
  | 'sedentary'
  | 'smoker'

export const HISTORY_ORDER: HistoryId[] = [
  'prediabetes',
  'hypothyroid',
  'vitdDeficiency',
  'dyslipidemia',
  'hypertension',
  'sedentary',
  'smoker',
]

export interface Subject {
  sex: Sex
  age: number
  heightCm: number
  weightKg: number
  history: HistoryId[]
}

export const DEFAULT_SUBJECT: Subject = {
  sex: 'male',
  age: 52,
  heightCm: 176,
  weightKg: 91,
  history: ['prediabetes', 'vitdDeficiency', 'sedentary'],
}

export function bmiOf(subject: Subject): number {
  const m = subject.heightCm / 100
  return subject.weightKg / (m * m)
}

export type BmiClass = 'under' | 'normal' | 'over' | 'obese'

export function bmiClass(bmi: number): BmiClass {
  if (bmi < 18.5) return 'under'
  if (bmi < 25) return 'normal'
  if (bmi < 30) return 'over'
  return 'obese'
}

type Shifts = Partial<Record<IndicatorId, number>>

/** Female relative to the catalogue, which is written for an adult male. */
const FEMALE: Shifts = {
  hgb: -1.4,
  hct: -4.6,
  rbc: -0.46,
  ferritin: -82,
  iron: -9,
  tsat: -5,
  testosterone: -455,
  shbg: 18,
  dheas: -48,
  urate: -1.05,
  creatinine: -0.16,
  egfr: 4,
  bodyfat: 8.5,
  leanmass: -11,
  igf1: 6,
  hdl: 9,
}

/** Per year above 40. */
const PER_YEAR: Shifts = {
  glucose: 0.22,
  hba1c: 0.007,
  insulin: 0.05,
  sbp: 0.46,
  dbp: 0.12,
  ldl: 0.5,
  chol: 0.6,
  apob: 0.35,
  egfr: -0.72,
  creatinine: 0.003,
  testosterone: -4.2,
  dheas: -3.4,
  igf1: -1.7,
  vo2max: -0.33,
  hrv: -0.42,
  crp: 0.012,
  homocysteine: 0.06,
}

/** Per BMI unit above 22. */
const PER_BMI: Shifts = {
  glucose: 1.15,
  hba1c: 0.036,
  insulin: 1.2,
  homair: 0.29,
  fructosamine: 2.4,
  trig: 7.6,
  hdl: -1.15,
  ldl: 2.2,
  chol: 2.6,
  apob: 1.6,
  nonhdl: 3.1,
  crp: 0.23,
  il6: 0.1,
  esr: 0.5,
  alt: 1.5,
  ast: 0.8,
  ggt: 1.45,
  leptin: 1.95,
  sbp: 0.95,
  dbp: 0.58,
  urate: 0.12,
  waist: 2.5,
  bodyfat: 0.85,
  vo2max: -0.72,
  hrv: -0.55,
  restinghr: 0.55,
  sleep: -0.035,
  testosterone: -9,
  shbg: -0.9,
}

const HISTORY: Record<HistoryId, Shifts> = {
  prediabetes: {
    glucose: 14,
    hba1c: 0.5,
    insulin: 5.2,
    homair: 1.45,
    cpeptide: 0.6,
    fructosamine: 26,
  },
  hypothyroid: {
    tsh: 4.4,
    ft4: -0.28,
    ft3: -0.52,
    tpoab: 135,
    tgab: 40,
    chol: 28,
    ldl: 22,
    restinghr: -6,
    hrv: -4,
  },
  vitdDeficiency: { vitd: -16, pth: 19, calcium: -0.16, magnesium: -0.08 },
  dyslipidemia: { chol: 42, ldl: 38, apob: 26, nonhdl: 40, trig: 46, hdl: -6, lpa: 18 },
  hypertension: { sbp: 17, dbp: 9.5, restinghr: 3, egfr: -5 },
  sedentary: { activity: -3300, vo2max: -5.6, hrv: -8.5, restinghr: 6, hdl: -4, homair: 0.3 },
  smoker: {
    crp: 1.1,
    fibrinogen: 0.5,
    homocysteine: 1.8,
    hgb: 0.6,
    hct: 2.1,
    wbc: 1.5,
    neut: 0.9,
    hdl: -5,
    vo2max: -3.2,
    b12: -60,
  },
}

/** Analytes that cannot go negative or zero without becoming nonsense. */
function clampToPlausible(id: IndicatorId, value: number): number {
  const indicator = INDICATORS.find((i) => i.id === id)!
  // never let a modifier stack drive an analyte to a value the assay could not
  // return; a tenth of the catalogue baseline is well below any reference floor
  return Math.max(indicator.baseline * 0.1, value)
}

export type Baselines = Record<IndicatorId, number>

/**
 * The subject's biochemical starting point.
 *
 * Modifiers are additive in each analyte's own unit and stack — a sedentary
 * smoker with a BMI of 31 gets all three. Anthropometry is not modelled at all:
 * weight, BMI and lean mass are simply what the subject is.
 */
export function baselinesOf(subject: Subject): Baselines {
  const bmi = bmiOf(subject)
  const overBmi = bmi - 22
  const overAge = subject.age - 40

  const out = {} as Baselines
  for (const indicator of INDICATORS) out[indicator.id] = indicator.baseline

  const apply = (shifts: Shifts, scale: number) => {
    for (const key of Object.keys(shifts) as IndicatorId[]) {
      out[key] += (shifts[key] as number) * scale
    }
  }

  if (subject.sex === 'female') apply(FEMALE, 1)
  apply(PER_YEAR, overAge)
  apply(PER_BMI, overBmi)
  for (const flag of subject.history) apply(HISTORY[flag], 1)

  out.weight = subject.weightKg
  out.bmi = bmi
  out.bodyfat = clampToPlausible('bodyfat', out.bodyfat)
  out.leanmass = subject.weightKg * (1 - out.bodyfat / 100)

  for (const key of Object.keys(out) as IndicatorId[]) {
    out[key] = clampToPlausible(key, out[key])
  }
  return out
}

/** Sex-specific reference bounds, where the catalogue's single range is wrong. */
const FEMALE_REFERENCE: Partial<Record<IndicatorId, [number, number]>> = {
  hgb: [12.0, 15.5],
  hct: [35, 45],
  rbc: [3.9, 5.2],
  ferritin: [15, 200],
  testosterone: [15, 70],
  creatinine: [0.5, 0.95],
  urate: [2.5, 6.0],
  hdl: [50, 100],
  bodyfat: [21, 33],
}

export function referenceFor(
  subject: Subject,
  id: IndicatorId,
): [number, number] | undefined {
  if (subject.sex === 'female') {
    const own = FEMALE_REFERENCE[id]
    if (own) return own
  }
  return INDICATORS.find((i) => i.id === id)?.reference
}

/** Whether a value sits below, inside or above its reference interval. */
export type Flag = 'low' | 'ok' | 'high'

export function flagOf(subject: Subject, id: IndicatorId, value: number): Flag {
  const range = referenceFor(subject, id)
  if (!range) return 'ok'
  if (value < range[0]) return 'low'
  if (value > range[1]) return 'high'
  return 'ok'
}

/** The analytes the subject card prints, in reading order. */
export const SNAPSHOT_PANEL: IndicatorId[] = [
  'glucose',
  'hba1c',
  'homair',
  'insulin',
  'chol',
  'ldl',
  'hdl',
  'trig',
  'tsh',
  'ft4',
  'vitd',
  'crp',
  'alt',
  'egfr',
  'sbp',
  'hgb',
]
