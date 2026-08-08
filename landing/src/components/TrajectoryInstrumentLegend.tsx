import type { ReactNode } from 'react'
import { useI18n } from '../i18n'

interface Props {
  extra?: ReactNode
}

/** Shared instrument legend for hero and live ensemble rig plates. */
export function TrajectoryInstrumentLegend({ extra }: Props) {
  const { t } = useI18n()
  const f = t.hero.figure

  return (
    <div className="legend">
      <span className="legend__item">
        <svg className="legend__swatch" viewBox="0 0 22 8" aria-hidden="true">
          <circle
            cx="11"
            cy="4"
            r="3.2"
            fill="none"
            strokeWidth="1.2"
            style={{ stroke: 'var(--accent-hi)' }}
          />
        </svg>
        {f.legendCheckpoint}
      </span>
      <span className="legend__item">
        <svg className="legend__swatch" viewBox="0 0 22 8" aria-hidden="true">
          <line
            x1="11"
            y1="0"
            x2="11"
            y2="8"
            strokeWidth="1.4"
            style={{ stroke: 'var(--accent)' }}
          />
        </svg>
        {f.legendIntervention}
      </span>
      <span className="legend__item">
        <svg className="legend__swatch" viewBox="0 0 22 8" aria-hidden="true">
          <line
            x1="0"
            y1="4"
            x2="22"
            y2="4"
            strokeWidth="1"
            strokeDasharray="3 3"
            style={{ stroke: 'var(--branch-d-ink)' }}
          />
        </svg>
        {f.legendUncertainty}
      </span>
      <span className="legend__item">
        <svg className="legend__swatch" viewBox="0 0 22 8" aria-hidden="true">
          <line
            x1="0"
            y1="4"
            x2="22"
            y2="4"
            strokeWidth="1.4"
            style={{ stroke: 'var(--branch-c)' }}
          />
        </svg>
        {f.legendMedian}
      </span>
      {extra}
    </div>
  )
}
