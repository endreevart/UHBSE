/**
 * Illustrative analyte catalogue for the engine demo.
 *
 * The point of the panel is scale: a protocol is never a single-target action,
 * and a demo built on six indicators cannot show that. Values are plausible
 * adult reference figures, not clinical data — see the disclaimer in the UI.
 *
 * `label` is the canonical short form a lab report prints. It stays untranslated
 * on purpose: analyte abbreviations are the same on a report in any language.
 * The handful of indicators that carry a translated long name override it.
 */

export type SystemId =
  | 'thyroid'
  | 'glycemic'
  | 'lipids'
  | 'inflammation'
  | 'micronutrients'
  | 'hepatorenal'
  | 'hematology'
  | 'endocrine'
  | 'anthropometry'

export interface IndicatorDef {
  system: SystemId
  /** short form as printed on a lab report */
  label: string
  unit: string
  baseline: number
  decimals: number
  /** short-term biological variability of the measurement itself */
  noise: number
  /** 1-sigma model uncertainty at the end of the horizon */
  sigma: number
  /** reference interval, where one is meaningful */
  reference?: [number, number]
}

const DEFS = {
  // ------------------------------------------------------------ thyroid axis
  tsh: { system: 'thyroid', label: 'TSH', unit: 'mIU/L', baseline: 1.82, decimals: 2, noise: 0.06, sigma: 0.5, reference: [0.4, 4.0] },
  ft4: { system: 'thyroid', label: 'FT4', unit: 'ng/dL', baseline: 1.24, decimals: 2, noise: 0.02, sigma: 0.14, reference: [0.8, 1.8] },
  ft3: { system: 'thyroid', label: 'FT3', unit: 'pg/mL', baseline: 3.1, decimals: 2, noise: 0.05, sigma: 0.3, reference: [2.3, 4.2] },
  rt3: { system: 'thyroid', label: 'rT3', unit: 'ng/dL', baseline: 18, decimals: 0, noise: 0.4, sigma: 2.6, reference: [10, 24] },
  tpoab: { system: 'thyroid', label: 'TPO-Ab', unit: 'IU/mL', baseline: 22, decimals: 0, noise: 1.1, sigma: 8, reference: [0, 34] },
  tgab: { system: 'thyroid', label: 'Tg-Ab', unit: 'IU/mL', baseline: 12, decimals: 0, noise: 0.8, sigma: 5, reference: [0, 40] },

  // ------------------------------------------------------- glycemic control
  glucose: { system: 'glycemic', label: 'Glucose', unit: 'mg/dL', baseline: 92, decimals: 0, noise: 1.6, sigma: 6, reference: [70, 99] },
  hba1c: { system: 'glycemic', label: 'HbA1c', unit: '%', baseline: 5.4, decimals: 2, noise: 0.03, sigma: 0.24, reference: [4.0, 5.6] },
  insulin: { system: 'glycemic', label: 'Insulin', unit: 'µIU/mL', baseline: 11.2, decimals: 1, noise: 0.5, sigma: 2.8, reference: [2.6, 24.9] },
  homair: { system: 'glycemic', label: 'HOMA-IR', unit: 'index', baseline: 2.54, decimals: 2, noise: 0.11, sigma: 0.7, reference: [0, 2.0] },
  cpeptide: { system: 'glycemic', label: 'C-peptide', unit: 'ng/mL', baseline: 2.4, decimals: 2, noise: 0.08, sigma: 0.45, reference: [1.1, 4.4] },
  fructosamine: { system: 'glycemic', label: 'Fructosamine', unit: 'µmol/L', baseline: 241, decimals: 0, noise: 3.2, sigma: 16, reference: [205, 285] },

  // ------------------------------------------------------------------ lipids
  chol: { system: 'lipids', label: 'Total cholesterol', unit: 'mg/dL', baseline: 208, decimals: 0, noise: 3.4, sigma: 16, reference: [0, 200] },
  ldl: { system: 'lipids', label: 'LDL-C', unit: 'mg/dL', baseline: 131, decimals: 0, noise: 2.8, sigma: 13, reference: [0, 100] },
  hdl: { system: 'lipids', label: 'HDL-C', unit: 'mg/dL', baseline: 48, decimals: 0, noise: 1.2, sigma: 5, reference: [40, 90] },
  trig: { system: 'lipids', label: 'Triglycerides', unit: 'mg/dL', baseline: 148, decimals: 0, noise: 6.5, sigma: 26, reference: [0, 150] },
  apob: { system: 'lipids', label: 'ApoB', unit: 'mg/dL', baseline: 98, decimals: 0, noise: 2.1, sigma: 9, reference: [0, 90] },
  nonhdl: { system: 'lipids', label: 'non-HDL-C', unit: 'mg/dL', baseline: 160, decimals: 0, noise: 3.1, sigma: 14, reference: [0, 130] },
  lpa: { system: 'lipids', label: 'Lp(a)', unit: 'nmol/L', baseline: 41, decimals: 0, noise: 1.4, sigma: 6, reference: [0, 75] },

  // ------------------------------------------------------------ inflammation
  crp: { system: 'inflammation', label: 'hs-CRP', unit: 'mg/L', baseline: 2.4, decimals: 2, noise: 0.14, sigma: 0.8, reference: [0, 1.0] },
  esr: { system: 'inflammation', label: 'ESR', unit: 'mm/h', baseline: 11, decimals: 0, noise: 0.7, sigma: 3.4, reference: [0, 15] },
  il6: { system: 'inflammation', label: 'IL-6', unit: 'pg/mL', baseline: 2.1, decimals: 2, noise: 0.1, sigma: 0.6, reference: [0, 1.8] },
  fibrinogen: { system: 'inflammation', label: 'Fibrinogen', unit: 'g/L', baseline: 3.4, decimals: 2, noise: 0.07, sigma: 0.4, reference: [2.0, 4.0] },
  homocysteine: { system: 'inflammation', label: 'Homocysteine', unit: 'µmol/L', baseline: 12.4, decimals: 1, noise: 0.35, sigma: 1.8, reference: [0, 10] },
  // an acute-phase reactant as much as an iron store, so it sits with inflammation
  ferritin: { system: 'inflammation', label: 'Ferritin', unit: 'ng/mL', baseline: 168, decimals: 0, noise: 5.5, sigma: 30, reference: [30, 300] },

  // ---------------------------------------------------------- micronutrients
  vitd: { system: 'micronutrients', label: '25(OH)D', unit: 'ng/mL', baseline: 32, decimals: 0, noise: 0.9, sigma: 7, reference: [30, 60] },
  pth: { system: 'micronutrients', label: 'PTH', unit: 'pg/mL', baseline: 48, decimals: 0, noise: 1.5, sigma: 7.5, reference: [15, 65] },
  calcium: { system: 'micronutrients', label: 'Calcium', unit: 'mg/dL', baseline: 9.4, decimals: 2, noise: 0.05, sigma: 0.22, reference: [8.6, 10.2] },
  magnesium: { system: 'micronutrients', label: 'Magnesium', unit: 'mg/dL', baseline: 2.02, decimals: 2, noise: 0.03, sigma: 0.12, reference: [1.7, 2.4] },
  zinc: { system: 'micronutrients', label: 'Zinc', unit: 'µg/dL', baseline: 84, decimals: 0, noise: 2.2, sigma: 9, reference: [70, 120] },
  b12: { system: 'micronutrients', label: 'Vitamin B12', unit: 'pg/mL', baseline: 412, decimals: 0, noise: 9, sigma: 55, reference: [200, 900] },
  folate: { system: 'micronutrients', label: 'Folate', unit: 'ng/mL', baseline: 9.6, decimals: 1, noise: 0.3, sigma: 1.8, reference: [3.0, 20] },
  iron: { system: 'micronutrients', label: 'Iron', unit: 'µg/dL', baseline: 94, decimals: 0, noise: 4.5, sigma: 17, reference: [60, 170] },
  tibc: { system: 'micronutrients', label: 'TIBC', unit: 'µg/dL', baseline: 318, decimals: 0, noise: 5, sigma: 22, reference: [250, 450] },
  tsat: { system: 'micronutrients', label: 'Transferrin sat.', unit: '%', baseline: 29, decimals: 0, noise: 1.3, sigma: 5, reference: [20, 50] },

  // ------------------------------------------------------- hepatic and renal
  alt: { system: 'hepatorenal', label: 'ALT', unit: 'U/L', baseline: 31, decimals: 0, noise: 1.4, sigma: 6.5, reference: [0, 33] },
  ast: { system: 'hepatorenal', label: 'AST', unit: 'U/L', baseline: 24, decimals: 0, noise: 1.1, sigma: 4.5, reference: [0, 32] },
  ggt: { system: 'hepatorenal', label: 'GGT', unit: 'U/L', baseline: 34, decimals: 0, noise: 1.6, sigma: 7, reference: [0, 40] },
  alp: { system: 'hepatorenal', label: 'ALP', unit: 'U/L', baseline: 78, decimals: 0, noise: 2.1, sigma: 9, reference: [35, 105] },
  bilirubin: { system: 'hepatorenal', label: 'Bilirubin', unit: 'mg/dL', baseline: 0.72, decimals: 2, noise: 0.04, sigma: 0.16, reference: [0.2, 1.2] },
  albumin: { system: 'hepatorenal', label: 'Albumin', unit: 'g/dL', baseline: 4.4, decimals: 2, noise: 0.04, sigma: 0.2, reference: [3.5, 5.2] },
  creatinine: { system: 'hepatorenal', label: 'Creatinine', unit: 'mg/dL', baseline: 0.92, decimals: 2, noise: 0.02, sigma: 0.1, reference: [0.6, 1.1] },
  egfr: { system: 'hepatorenal', label: 'eGFR', unit: 'mL/min', baseline: 92, decimals: 0, noise: 1.8, sigma: 8, reference: [90, 130] },
  urea: { system: 'hepatorenal', label: 'Urea', unit: 'mg/dL', baseline: 32, decimals: 0, noise: 1.5, sigma: 5.5, reference: [17, 43] },
  urate: { system: 'hepatorenal', label: 'Uric acid', unit: 'mg/dL', baseline: 5.8, decimals: 2, noise: 0.13, sigma: 0.7, reference: [3.5, 7.2] },

  // -------------------------------------------------------------- hematology
  hgb: { system: 'hematology', label: 'Hemoglobin', unit: 'g/dL', baseline: 14.2, decimals: 1, noise: 0.12, sigma: 0.7, reference: [13.0, 17.0] },
  hct: { system: 'hematology', label: 'Hematocrit', unit: '%', baseline: 42.4, decimals: 1, noise: 0.35, sigma: 1.9, reference: [39, 50] },
  rbc: { system: 'hematology', label: 'RBC', unit: '10¹²/L', baseline: 4.82, decimals: 2, noise: 0.04, sigma: 0.22, reference: [4.3, 5.9] },
  mcv: { system: 'hematology', label: 'MCV', unit: 'fL', baseline: 88, decimals: 0, noise: 0.5, sigma: 2.4, reference: [80, 100] },
  platelets: { system: 'hematology', label: 'Platelets', unit: '10⁹/L', baseline: 246, decimals: 0, noise: 6, sigma: 28, reference: [150, 400] },
  wbc: { system: 'hematology', label: 'WBC', unit: '10⁹/L', baseline: 6.4, decimals: 2, noise: 0.2, sigma: 0.9, reference: [4.0, 10.0] },
  neut: { system: 'hematology', label: 'Neutrophils', unit: '10⁹/L', baseline: 3.6, decimals: 2, noise: 0.15, sigma: 0.65, reference: [1.8, 7.0] },
  lymph: { system: 'hematology', label: 'Lymphocytes', unit: '10⁹/L', baseline: 2.1, decimals: 2, noise: 0.09, sigma: 0.4, reference: [1.0, 4.0] },

  // ---------------------------------------------------------------- endocrine
  cortisol: { system: 'endocrine', label: 'Cortisol AM', unit: 'µg/dL', baseline: 14.6, decimals: 1, noise: 0.6, sigma: 2.6, reference: [6, 19] },
  dheas: { system: 'endocrine', label: 'DHEA-S', unit: 'µg/dL', baseline: 214, decimals: 0, noise: 5.5, sigma: 28, reference: [80, 560] },
  testosterone: { system: 'endocrine', label: 'Testosterone', unit: 'ng/dL', baseline: 486, decimals: 0, noise: 14, sigma: 68, reference: [300, 950] },
  shbg: { system: 'endocrine', label: 'SHBG', unit: 'nmol/L', baseline: 34, decimals: 0, noise: 1.1, sigma: 5.5, reference: [18, 54] },
  igf1: { system: 'endocrine', label: 'IGF-1', unit: 'ng/mL', baseline: 168, decimals: 0, noise: 4.2, sigma: 22, reference: [94, 252] },
  leptin: { system: 'endocrine', label: 'Leptin', unit: 'ng/mL', baseline: 14.8, decimals: 1, noise: 0.6, sigma: 3.4, reference: [1.2, 22] },
  prolactin: { system: 'endocrine', label: 'Prolactin', unit: 'ng/mL', baseline: 11.4, decimals: 1, noise: 0.45, sigma: 2.4, reference: [4, 18] },

  // ---------------------------------------------- anthropometry and function
  weight: { system: 'anthropometry', label: 'Body weight', unit: 'kg', baseline: 72.4, decimals: 1, noise: 0.25, sigma: 2.2 },
  bmi: { system: 'anthropometry', label: 'BMI', unit: 'kg/m²', baseline: 23.6, decimals: 2, noise: 0.08, sigma: 0.72, reference: [18.5, 25] },
  waist: { system: 'anthropometry', label: 'Waist', unit: 'cm', baseline: 88, decimals: 0, noise: 0.4, sigma: 2.6, reference: [0, 94] },
  bodyfat: { system: 'anthropometry', label: 'Body fat', unit: '%', baseline: 24.8, decimals: 1, noise: 0.3, sigma: 1.6, reference: [8, 25] },
  leanmass: { system: 'anthropometry', label: 'Lean mass', unit: 'kg', baseline: 54.4, decimals: 1, noise: 0.2, sigma: 1.2 },
  sbp: { system: 'anthropometry', label: 'Systolic BP', unit: 'mmHg', baseline: 128, decimals: 0, noise: 2.4, sigma: 6.5, reference: [0, 120] },
  dbp: { system: 'anthropometry', label: 'Diastolic BP', unit: 'mmHg', baseline: 82, decimals: 0, noise: 1.8, sigma: 4.5, reference: [0, 80] },
  restinghr: { system: 'anthropometry', label: 'Resting HR', unit: 'bpm', baseline: 68, decimals: 0, noise: 1.3, sigma: 4, reference: [50, 70] },
  hrv: { system: 'anthropometry', label: 'HRV (RMSSD)', unit: 'ms', baseline: 42, decimals: 0, noise: 1.9, sigma: 7.5 },
  vo2max: { system: 'anthropometry', label: 'VO₂max', unit: 'mL/kg/min', baseline: 36.2, decimals: 1, noise: 0.3, sigma: 2.1 },
  activity: { system: 'anthropometry', label: 'Daily steps', unit: 'steps', baseline: 7840, decimals: 0, noise: 320, sigma: 1400 },
  sleep: { system: 'anthropometry', label: 'Sleep duration', unit: 'h', baseline: 6.7, decimals: 2, noise: 0.12, sigma: 0.45, reference: [7, 9] },
} satisfies Record<string, IndicatorDef>

export type IndicatorId = keyof typeof DEFS

export interface Indicator extends IndicatorDef {
  id: IndicatorId
}

export const INDICATORS: Indicator[] = (Object.keys(DEFS) as IndicatorId[]).map((id) => ({
  id,
  ...(DEFS[id] as IndicatorDef),
}))

export const INDICATOR_BY_ID = Object.fromEntries(
  INDICATORS.map((i) => [i.id, i]),
) as Record<IndicatorId, Indicator>

/**
 * Three roughly equal stacks, so the heatmap uses the width of the page instead
 * of running a single seventy-row column down it.
 */
export const SYSTEM_COLUMNS: SystemId[][] = [
  ['thyroid', 'glycemic', 'lipids', 'inflammation'],
  ['micronutrients', 'hepatorenal'],
  ['hematology', 'endocrine', 'anthropometry'],
]
