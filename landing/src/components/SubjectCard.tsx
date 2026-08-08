import { formatValue, INDICATOR_BY_ID, type IndicatorId } from '../engine/model'
import {
  HISTORY_ORDER,
  SNAPSHOT_PANEL,
  bmiClass,
  bmiOf,
  flagOf,
  referenceFor,
  type Baselines,
  type HistoryId,
  type Subject,
} from '../engine/subject'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'

interface Props {
  subject: Subject
  baselines: Baselines
  onChange: (next: Subject) => void
}

/**
 * The person the run is about.
 *
 * Everything downstream starts here: the anthropometry and the history set the
 * biochemical starting point, and the snapshot below is that starting point
 * rather than a decorative table — change the weight and the panel moves.
 */
export function SubjectCard({ subject, baselines, onChange }: Props) {
  const { t, fmt } = useI18n()
  const bmi = bmiOf(subject)
  const cls = bmiClass(bmi)

  const patch = (next: Partial<Subject>) => onChange({ ...subject, ...next })

  const toggleHistory = (flag: HistoryId) => {
    patch({
      history: subject.history.includes(flag)
        ? subject.history.filter((f) => f !== flag)
        : [...subject.history, flag],
    })
  }

  const outOfRange = SNAPSHOT_PANEL.filter(
    (id) => flagOf(subject, id, baselines[id]) !== 'ok',
  ).length

  return (
    <div className="subject">
      <header className="lab__panel-head">
        <h3 className="lab__panel-title">{t.engine.subjectTitle}</h3>
        <span className="mono-label">
          {fmt(t.engine.subjectFlags, { n: outOfRange, total: SNAPSHOT_PANEL.length })}
        </span>
      </header>

      <div className="subject__grid">
        {/* ------------------------------------------------- anthropometry */}
        <div className="subject__body">
          <div className="subject__sex" role="group" aria-label={t.engine.sexLabel}>
            {(['male', 'female'] as const).map((sex) => (
              <button
                key={sex}
                type="button"
                className="lab__chip"
                data-on={subject.sex === sex}
                onClick={() => patch({ sex })}
              >
                {t.engine.sexes[sex]}
              </button>
            ))}
          </div>

          <Dial
            label={t.engine.ageLabel}
            value={subject.age}
            unit={t.engine.yearsShort}
            min={20}
            max={80}
            step={1}
            onChange={(age) => patch({ age })}
          />
          <Dial
            label={t.engine.heightLabel}
            value={subject.heightCm}
            unit={t.engine.cmShort}
            min={148}
            max={200}
            step={1}
            onChange={(heightCm) => patch({ heightCm })}
          />
          <Dial
            label={t.engine.weightLabel}
            value={subject.weightKg}
            unit={t.engine.kgShort}
            min={45}
            max={140}
            step={1}
            onChange={(weightKg) => patch({ weightKg })}
          />

          <div className="subject__bmi" data-class={cls}>
            <span className="mono-label">{t.engine.bmiLabel}</span>
            <b className="tabular">{bmi.toFixed(1)}</b>
            <span className="subject__bmi-class">{t.engine.bmiClasses[cls]}</span>
          </div>
        </div>

        {/* ------------------------------------------------------- history */}
        <div className="subject__history">
          <p className="mono-label subject__sub">{t.engine.historyTitle}</p>
          <div className="subject__flags">
            {HISTORY_ORDER.map((flag) => (
              <button
                key={flag}
                type="button"
                className="lab__chip"
                data-on={subject.history.includes(flag)}
                onClick={() => toggleHistory(flag)}
              >
                {t.engine.history[flag]}
              </button>
            ))}
          </div>
          <p className="subject__note">{t.engine.subjectNote}</p>
        </div>

        {/* ---------------------------------------------------- snapshot */}
        <div className="subject__snapshot">
          <p className="mono-label subject__sub">{t.engine.snapshotTitle}</p>
          <div className="subject__analytes">
            {SNAPSHOT_PANEL.map((id) => (
              <Analyte key={id} id={id} subject={subject} value={baselines[id]} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

interface DialProps {
  label: string
  value: number
  unit: string
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}

function Dial({ label, value, unit, min, max, step, onChange }: DialProps) {
  return (
    <label className="lab__field subject__dial">
      <span className="lab__field-label">
        {label}
        <b className="tabular">
          {value} {unit}
        </b>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

function Analyte({
  id,
  subject,
  value,
}: {
  id: IndicatorId
  subject: Subject
  value: number
}) {
  const { t } = useI18n()
  const indicator = INDICATOR_BY_ID[id]
  const flag = flagOf(subject, id, value)
  const range = referenceFor(subject, id)

  return (
    <div className="subject__analyte" data-flag={flag}>
      <span className="subject__analyte-name">{indicatorName(t, indicator)}</span>
      <span className="subject__analyte-value tabular">
        {formatValue(id, value)}
        <i className="subject__analyte-unit">{indicator.unit}</i>
      </span>
      {range && (
        <span className="subject__analyte-ref tabular">
          {formatValue(id, range[0])}–{formatValue(id, range[1])}
        </span>
      )}
    </div>
  )
}
