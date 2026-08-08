import { HORIZON_WEEKS } from '../engine/model'
import { useI18n } from '../i18n'
import { formatWeekSlot } from '../lib/weekFormat'

const STEP = 0.5

interface Props {
  cursorWeek: number
  horizonWeeks?: number
  onScrub: (week: number) => void
}

export function TimelineScrubber({ cursorWeek, horizonWeeks = HORIZON_WEEKS, onScrub }: Props) {
  const { t, fmt } = useI18n()

  return (
    <label className="rig__scrub">
      <span className="mono-label">{t.ws.scrubLabel}</span>
      <input
        type="range"
        className="rig__scrub-input"
        min={0}
        max={horizonWeeks}
        step={STEP}
        value={cursorWeek}
        onChange={(e) => onScrub(Number(e.target.value))}
        aria-valuetext={fmt(t.hero.figure.week, { n: formatWeekSlot(cursorWeek) })}
      />
      <b className="rig__scrub-readout tabular">
        {fmt(t.hero.figure.week, { n: formatWeekSlot(cursorWeek) })}
      </b>
    </label>
  )
}
