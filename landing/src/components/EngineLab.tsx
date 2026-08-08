import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import {
  HORIZON_WEEKS,
  INTERVENTIONS,
  INDICATOR_BY_ID,
  formatValue,
  type AppliedIntervention,
  type IndicatorId,
  type InterventionId,
} from '../engine/model'
import { runCohort, weekStatsForIndicator } from '../engine/cohort'
import { cohortMedianPanelBurden } from '../lib/branchComposite'
import type { FanAxisMode } from '../lib/simulationTree'
import {
  DEFAULT_SUBJECT,
  baselinesOf,
  bmiOf,
  flagOf,
  SNAPSHOT_PANEL,
  type Subject,
} from '../engine/subject'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'
import { BiomarkerPanel } from './BiomarkerPanel'
import { EnsembleFan } from './EnsembleFan'
import { Reveal } from './Reveal'
import { SubjectDrawer } from './SubjectDrawer'
import { TimelineScrubber } from './TimelineScrubber'
import { TrajectoryInstrumentLegend } from './TrajectoryInstrumentLegend'
import { formatWeekSlot } from '../lib/weekFormat'

let keyCounter = 0
const nextKey = () => `iv-${(keyCounter += 1)}`

const BASE_RATE = 2.6
const SPEEDS = [1, 2, 4]
const STEP = 0.5

function snapWeek(week: number): number {
  return Math.round(week * 2) / 2
}

function initialProtocol(): AppliedIntervention[] {
  return []
}

/**
 * Probability-first workspace: one subject, one protocol, thousands of lifestyle
 * branches from the cohort engine. The fan chart is the instrument; everything
 * else is configuration or readout.
 */
export function EngineLab() {
  const { t, fmt } = useI18n()
  const f = t.hero.figure
  const [subject, setSubject] = useState<Subject>(DEFAULT_SUBJECT)
  const [protocol, setProtocol] = useState<AppliedIntervention[]>(initialProtocol)
  const [displayId, setDisplayId] = useState<IndicatorId>('vitd')
  const [fanAxisMode, setFanAxisMode] = useState<FanAxisMode>('composite')
  const [cursorWeek, setCursorWeek] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [simResetToken, setSimResetToken] = useState(0)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedBranch, setSelectedBranch] = useState<number | null>(null)
  const [showFavorable, setShowFavorable] = useState(true)
  const [showUnfavorable, setShowUnfavorable] = useState(true)

  const baselines = useMemo(() => baselinesOf(subject), [subject])
  const bmi = bmiOf(subject)
  const outside = SNAPSHOT_PANEL.filter((id) => flagOf(subject, id, baselines[id]) !== 'ok').length
  const indicator = INDICATOR_BY_ID[displayId]

  const runInputs = useMemo(
    () => ({ subject, baselines, protocol }),
    [subject, baselines, protocol],
  )
  const settled = useDeferredValue(runInputs)
  const cohort = useMemo(() => runCohort(settled), [settled])
  const displayStats = useMemo(
    () => weekStatsForIndicator(cohort, displayId),
    [cohort, displayId],
  )

  const frame = useRef(0)
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const step = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      setCursorWeek((w) => {
        const next = w + dt * BASE_RATE * speed
        if (next >= HORIZON_WEEKS) {
          setPlaying(false)
          return HORIZON_WEEKS
        }
        return next
      })
      frame.current = requestAnimationFrame(step)
    }
    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
  }, [playing, speed])

  const scrub = useCallback((week: number) => {
    setPlaying(false)
    setCursorWeek(Math.max(0, Math.min(HORIZON_WEEKS, week)))
  }, [])

  const addDrug = useCallback((spec: InterventionId) => {
    const meta = INTERVENTIONS[spec]
    const startWeek = snapWeek(cursorWeek)
    setProtocol((list) => [...list, { key: nextKey(), spec, dose: meta.defaultDose, startWeek }])
    setSelectedBranch(null)
  }, [cursorWeek])

  const pickFanIndicator = useCallback(
    (id: IndicatorId) => {
      if (fanAxisMode === 'indicator' && displayId === id) {
        setFanAxisMode('composite')
        return
      }
      setDisplayId(id)
      setFanAxisMode('indicator')
    },
    [fanAxisMode, displayId],
  )

  const setDose = useCallback(
    (key: string, dose: number) => {
      const week = snapWeek(cursorWeek)
      setProtocol((list) => {
        const iv = list.find((item) => item.key === key)
        if (!iv || iv.dose === dose) return list

        // Segment entirely in the future — edit freely.
        if (iv.startWeek >= week - 0.001) {
          return list.map((item) => (item.key === key ? { ...item, dose } : item))
        }

        // Already closed in the past — dose edits must target the active segment.
        if (iv.endWeek !== undefined && iv.endWeek <= week + 0.001) return list

        // Active segment that started before playhead — freeze past, new dose from playhead.
        const closed: AppliedIntervention = { ...iv, endWeek: week }
        const successor: AppliedIntervention = {
          key: nextKey(),
          spec: iv.spec,
          dose,
          startWeek: week,
        }
        return list.map((item) => (item.key === key ? closed : item)).concat(successor)
      })
      setSelectedBranch(null)
    },
    [cursorWeek],
  )

  const setStartWeek = useCallback(
    (key: string, startWeek: number) => {
      const week = snapWeek(cursorWeek)
      const snapped = snapWeek(startWeek)
      setProtocol((list) =>
        list.map((iv) => {
          if (iv.key !== key) return iv
          if (iv.endWeek !== undefined && iv.endWeek <= week + 0.001) return iv
          if (iv.startWeek < week - 0.001) return iv
          return { ...iv, startWeek: Math.min(HORIZON_WEEKS, Math.max(0, snapped)) }
        }),
      )
      setSelectedBranch(null)
    },
    [cursorWeek],
  )

  const removeDrug = useCallback((key: string) => {
    setProtocol((list) => list.filter((iv) => iv.key !== key))
    setSelectedBranch(null)
  }, [])

  const resetSimulation = useCallback(() => {
    cancelAnimationFrame(frame.current)
    setPlaying(false)
    setCursorWeek(0)
    setSpeed(1)
    setProtocol(initialProtocol())
    setSelectedBranch(null)
    setShowFavorable(true)
    setShowUnfavorable(true)
    setFanAxisMode('composite')
    setSimResetToken((n) => n + 1)
  }, [])

  const week = Math.round(cursorWeek * 2) / 2
  const weekText = formatWeekSlot(week)
  const weekIdx = Math.min(HORIZON_WEEKS, Math.round(cursorWeek))
  const census = cohort.stats[weekIdx]
  const indicatorStat = displayStats[weekIdx]
  const compositeBurden = useMemo(
    () => cohortMedianPanelBurden(cohort, weekIdx, baselines, subject),
    [cohort, weekIdx, baselines, subject],
  )

  return (
    <section className="section section--flush lab-section" id="engine">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.engine.kicker}</p>
          <h2 className="display display--l">{t.engine.title}</h2>
          <p className="lede">{t.ws.ensembleLead}</p>
        </Reveal>

        <Reveal className="rig plate ws--rig" data-hints="false">
          <div className="rig__gate">
            <div className="rig__gate-surface">
          <div className="rig__bar">
            <span className="rig__meta">
              <button type="button" className="rig__chip" onClick={() => setDrawerOpen(true)}>
                <i>{f.subject}</i>
                <b>
                  S-0042 · {t.engine.sexes[subject.sex]} · {subject.age} {t.engine.yearsShort} · BMI{' '}
                  {bmi.toFixed(1)}
                  {outside > 0 && (
                    <span className="rig__chip-flag tabular">
                      {outside}/{SNAPSHOT_PANEL.length}
                    </span>
                  )}
                </b>
              </button>
              <span className="rig__meta-stats">
                {[
                  { key: 'horizon', label: f.horizon, value: `${HORIZON_WEEKS} ${t.engine.weekShort}`, tone: 'wide' },
                  { key: 'branches', label: f.branches, value: cohort.count.toLocaleString('en-US'), tone: 'num3' },
                  { key: 'step', label: f.step, value: `${STEP} ${t.engine.weekShort}`, tone: 'wide' },
                  { key: 'week', label: t.ws.week, value: weekText, tone: 'week' },
                  {
                    key: 'indicator',
                    label:
                      fanAxisMode === 'composite'
                        ? t.ws.fanAxisCompositeLabel
                        : indicatorName(t, indicator),
                    value:
                      fanAxisMode === 'composite'
                        ? compositeBurden.toFixed(2)
                        : formatValue(displayId, indicatorStat.p50),
                    tone: 'metric',
                  },
                ].map(({ key, label, value, tone }) => (
                  <span className={`rig__stat rig__stat--${tone}`} key={key}>
                    <i>{label}</i>
                    <b className="tabular">{value}</b>
                  </span>
                ))}
              </span>
            </span>
          </div>

          <div className="rig__deck rig__deck--transport">
            <div className="rig__transport figure-ltr" dir="ltr">
              <TimelineScrubber cursorWeek={cursorWeek} onScrub={scrub} />
              <div className="rig__keys">
                <button type="button" className="rig__key" onClick={() => scrub(0)} aria-label="⏮">
                  <svg viewBox="0 0 12 12" aria-hidden="true">
                    <path d="M2 1v10M11 1L4 6l7 5z" />
                  </svg>
                </button>
                <button type="button" className="rig__key" onClick={() => scrub(cursorWeek - STEP)} aria-label="◀">
                  <svg viewBox="0 0 12 12" aria-hidden="true">
                    <path d="M10 1L3 6l7 5z" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="rig__key rig__key--go"
                  onClick={() => setPlaying((p) => !p)}
                  aria-label={playing ? t.engine.runPause : t.engine.runResume}
                >
                  {playing ? (
                    <svg viewBox="0 0 12 12" aria-hidden="true">
                      <path d="M2 1h3v10H2zM7 1h3v10H7z" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 12 12" aria-hidden="true">
                      <path d="M2 1l9 5-9 5z" />
                    </svg>
                  )}
                </button>
                <button type="button" className="rig__key" onClick={() => scrub(cursorWeek + STEP)} aria-label="▶">
                  <svg viewBox="0 0 12 12" aria-hidden="true">
                    <path d="M2 1l7 5-7 5z" />
                  </svg>
                </button>
                <button type="button" className="rig__key" onClick={() => scrub(HORIZON_WEEKS)} aria-label="⏭">
                  <svg viewBox="0 0 12 12" aria-hidden="true">
                    <path d="M10 1v10M1 1l7 5-7 5z" />
                  </svg>
                </button>
              </div>
              <div className="rig__speeds" role="group" aria-label={t.ws.speed}>
                <span className="mono-label">{t.ws.speed}</span>
                {SPEEDS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="rig__speed"
                    data-on={speed === s}
                    onClick={() => setSpeed(s)}
                  >
                    {s}×
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="rig__reset"
                onClick={resetSimulation}
                title={t.engine.reset}
              >
                {t.engine.reset}
              </button>
              <span className="rig__census" aria-label={fmt(t.ws.ensembleCensus, {
                active: census.active.toLocaleString('en-US'),
                stopped: census.stopped.toLocaleString('en-US'),
                improved: census.improved.toLocaleString('en-US'),
              })}>
                <span className="rig__census-part">
                  <b className="rig__census-n tabular">{census.active.toLocaleString('en-US')}</b>
                  <i>{t.ws.censusActiveLabel}</i>
                </span>
                <span className="rig__census-sep" aria-hidden="true">
                  ·
                </span>
                <span className="rig__census-part">
                  <b className="rig__census-n tabular">{census.stopped.toLocaleString('en-US')}</b>
                  <i>{t.ws.censusStoppedLabel}</i>
                </span>
                <span className="rig__census-sep" aria-hidden="true">
                  ·
                </span>
                <span className="rig__census-part">
                  <b className="rig__census-n tabular">{census.improved.toLocaleString('en-US')}</b>
                  <i>{t.ws.censusImprovedLabel}</i>
                </span>
              </span>
            </div>
          </div>

          <div className="rig__body rig__body--split">
            <EnsembleFan
              result={cohort}
              baselines={baselines}
              subject={subject}
              protocol={protocol}
              indicatorId={displayId}
              fanAxisMode={fanAxisMode}
              onFanAxisMode={setFanAxisMode}
              cursorWeek={cursorWeek}
              simulationEndWeek={HORIZON_WEEKS}
              simResetToken={simResetToken}
              selectedBranch={selectedBranch}
              showFavorable={showFavorable}
              showUnfavorable={showUnfavorable}
              onShowFavorable={setShowFavorable}
              onShowUnfavorable={setShowUnfavorable}
              onCursorChange={scrub}
              onSelectBranch={setSelectedBranch}
              onAddDrug={addDrug}
              onDose={setDose}
              onStartWeek={setStartWeek}
              onRemoveDrug={removeDrug}
            />
            <BiomarkerPanel
              result={cohort}
              subject={subject}
              baselines={baselines}
              displayId={displayId}
              fanAxisMode={fanAxisMode}
              cursorWeek={cursorWeek}
              selectedBranch={selectedBranch}
              onPickIndicator={pickFanIndicator}
            />
          </div>

          <div className="rig__foot">
            <TrajectoryInstrumentLegend
              extra={
                <>
                  <span className="legend__item">
                    <svg className="legend__swatch" viewBox="0 0 22 8" aria-hidden="true">
                      <line
                        x1="0"
                        y1="4"
                        x2="22"
                        y2="4"
                        strokeWidth="1.6"
                        style={{ stroke: 'var(--branch-a)' }}
                      />
                    </svg>
                    {t.ws.legendImproved}
                  </span>
                  <span className="legend__item">
                    <svg className="legend__swatch" viewBox="0 0 22 8" aria-hidden="true">
                      <line
                        x1="0"
                        y1="4"
                        x2="22"
                        y2="4"
                        strokeWidth="0.9"
                        opacity="0.45"
                        style={{ stroke: 'var(--ink-ghost)' }}
                      />
                    </svg>
                    {t.ws.legendOther}
                  </span>
                </>
              }
            />
          </div>
            </div>
            <div className="rig__gate-overlay" role="status">
              <p className="rig__gate-title">{t.engine.desktopOnlyTitle}</p>
              <p className="rig__gate-lede">{t.engine.desktopOnlyBody}</p>
            </div>
          </div>
        </Reveal>
      </div>

      <SubjectDrawer
        open={drawerOpen}
        subject={subject}
        baselines={baselines}
        onClose={() => setDrawerOpen(false)}
        onChange={setSubject}
      />
    </section>
  )
}
