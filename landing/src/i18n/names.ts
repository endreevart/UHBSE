import type { Indicator, IndicatorId, SystemId } from '../engine/indicators'
import type { Dict } from './locales/en'

/**
 * Analyte abbreviations are the same on a lab report in any language, so only
 * the handful of indicators the narrative actually names carry a translation.
 * Everything else falls back to the canonical short form.
 */
export function indicatorName(t: Dict, indicator: Indicator): string {
  const named = t.engine.indicators as Partial<Record<IndicatorId, string>>
  return named[indicator.id] ?? indicator.label
}

export function systemName(t: Dict, system: SystemId): string {
  return t.engine.systems[system]
}
