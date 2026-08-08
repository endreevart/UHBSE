import {
  INTERVENTIONS,
  effectClaims,
  formatValue,
  type InterventionId,
} from '../engine/model'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'

interface Props {
  spec: InterventionId
}

/**
 * Where an intervention's numbers come from.
 *
 * An engine that moves seventy indicators on the strength of four protocols has
 * to be able to answer "on what basis". Each effect is shown as an interval
 * rather than a point, and the badge says plainly whether the estimate was read
 * out of the source data, entered from a guideline, or — as everywhere on this
 * page — invented for the demonstration.
 */
export function EvidenceCard({ spec }: Props) {
  const { t, fmt } = useI18n()
  const meta = INTERVENTIONS[spec]
  const { origin, status, source, spread } = meta.provenance
  const claims = effectClaims(spec)

  return (
    <div className="evidence">
      <div className="evidence__badges">
        <span className="evidence__badge" data-origin={origin}>
          {t.engine.origins[origin]}
        </span>
        <span className="evidence__badge" data-status={status}>
          {t.engine.statuses[status]}
        </span>
        <span className="mono-label evidence__source">{source}</span>
      </div>

      <p className="evidence__note">
        {fmt(t.engine.evidenceNote, {
          dose: `${meta.refDose.toLocaleString('en-US')} ${t.engine.interventionUnits[spec]}`,
          pct: Math.round(spread * 100),
        })}
      </p>

      <ul className="evidence__claims">
        {claims.map((claim) => {
          // the sign is carried by the point estimate, so the interval is shown
          // as magnitudes and has to run from the smaller one to the larger
          const ends = [Math.abs(claim.lo), Math.abs(claim.hi)].sort((a, b) => a - b)
          return (
            <li className="evidence__claim" key={claim.indicator.id}>
              <span className="evidence__claim-name">{indicatorName(t, claim.indicator)}</span>
              <span className="evidence__claim-value tabular">
                {claim.effect > 0 ? '+' : '−'}
                {formatValue(claim.indicator.id, Math.abs(claim.effect))}
                <span className="evidence__claim-range">
                  {formatValue(claim.indicator.id, ends[0])} –{' '}
                  {formatValue(claim.indicator.id, ends[1])}
                </span>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
