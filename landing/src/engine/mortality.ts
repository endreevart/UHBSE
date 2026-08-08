import type { Subject } from './subject'

/** stopReason sentinel — not a vital index. */
export const SENESCENCE_STOP = 127

export const MAX_AGE_MALE = 92
export const MAX_AGE_FEMALE = 95

function unitRandom(branchKey: number, salt: number): number {
  const x = Math.sin(branchKey * 12.9898 + salt * 78.233) * 43_758.5453
  return x - Math.floor(x)
}

/** Hard ceiling from calendar age — cannot simulate past this. */
export function maxWeeksUntilMaxAge(subject: Subject): number {
  const capAge = subject.sex === 'female' ? MAX_AGE_FEMALE : MAX_AGE_MALE
  const yearsLeft = capAge - subject.age
  if (yearsLeft <= 0) return 0
  return Math.floor(yearsLeft * 52)
}

/**
 * Deterministic lifespan for one lifestyle branch.
 * Worse lifestyle and lower random quantile → earlier senescence stop.
 */
export function branchSenescenceWeek(
  subject: Subject,
  branchKey: number,
  badness: number,
): number {
  const hardCap = maxWeeksUntilMaxAge(subject)
  if (hardCap <= 0) return 0

  const midYears = Math.max(
    0.75,
    (subject.sex === 'female' ? 86.5 : 82.5) - subject.age - badness * 6.5,
  )
  const u = unitRandom(branchKey, 41)
  const ratio = Math.exp((u - 0.5) * 3.8)
  const capAge = subject.sex === 'female' ? MAX_AGE_FEMALE : MAX_AGE_MALE
  const spanYears = Math.min(midYears * ratio, Math.max(0.5, capAge - subject.age))
  const weeks = Math.floor(spanYears * 52)

  return Math.min(hardCap, Math.max(8, weeks))
}

export function isSenescenceStop(reason: number): boolean {
  return reason === SENESCENCE_STOP
}

export function ageAtWeek(subject: Subject, week: number): number {
  return subject.age + week / 52
}
