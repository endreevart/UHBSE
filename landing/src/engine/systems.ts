import type { EffectRow } from './model'
import type { IndicatorId, SystemId } from './indicators'

/**
 * How hard the protocol is pushing on each measured system right now.
 *
 * Seventy analytes ranked in one list is a spreadsheet. Grouped into the
 * systems they belong to, the same seventy answer the question a list cannot:
 * not "which number moved most" but "where in this person is the protocol
 * landing", which is what the workspace opens on.
 */

/* ------------------------------------------------------------------ load */

export interface SystemLoad {
  system: SystemId
  /** total absolute movement across the system, in sigma */
  load: number
  /** signed sum, for the direction of the marker */
  signed: number
  /** indicators that moved enough to be worth naming */
  moved: number
  count: number
  /** fraction of the whole body's movement, 0..1 */
  share: number
  indicators: { id: IndicatorId; sigma: number }[]
}

/** Below this an indicator is inside its own week-to-week wobble. */
const FLOOR = 0.22

/**
 * How hard each system is being pushed at one week.
 *
 * Reads the effect grid the workspace already computes once per protocol
 * change, so putting seventy analytes on a body costs one pass over an array
 * rather than seventy simulations per frame.
 */
export function systemLoads(rows: EffectRow[], week: number): SystemLoad[] {
  const w = Math.max(0, Math.min((rows[0]?.weekly.length ?? 1) - 1, Math.round(week)))
  const groups = new Map<SystemId, SystemLoad>()

  for (const row of rows) {
    const system = row.indicator.system
    const sigma = row.weekly[w] ?? 0
    let group = groups.get(system)
    if (!group) {
      group = { system, load: 0, signed: 0, moved: 0, count: 0, share: 0, indicators: [] }
      groups.set(system, group)
    }
    group.count += 1
    group.load += Math.abs(sigma)
    group.signed += sigma
    if (Math.abs(sigma) >= FLOOR) group.moved += 1
    group.indicators.push({ id: row.indicator.id, sigma })
  }

  const total = [...groups.values()].reduce((sum, g) => sum + g.load, 0)
  for (const group of groups.values()) {
    group.share = total > 0 ? group.load / total : 0
    group.indicators.sort((a, b) => Math.abs(b.sigma) - Math.abs(a.sigma))
  }

  return [...groups.values()].sort((a, b) => b.load - a.load)
}
