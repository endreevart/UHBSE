import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  HORIZON_WEEKS,
  INDICATOR_BY_ID,
  formatValue,
  type AppliedIntervention,
  type IndicatorId,
  type InterventionId,
} from '../engine/model'
import { type RunResult } from '../engine/cohort'
import type { Baselines, Subject } from '../engine/subject'
import { useEnsembleGl } from '../hooks/useEnsembleGl'
import { useI18n } from '../i18n'
import { indicatorName } from '../i18n/names'
import { pickBestBranch } from '../lib/branchComposite'
import {
  FAN_ZOOM_STEP,
  clampFanZoom,
  constrainFanView,
  defaultFanView,
  fanCameraRect,
  fitFullTimelineView,
  isFullTimelineVisible,
  resetFanView,
  visibleSpanLabel,
  fixedLabelTransform,
  isInViewX,
  worldUiScale,
  zoomToTimelineSpan,
  ZOOM_PRESET_DAY_WEEKS,
  type FanView,
} from '../lib/ensembleViewport'
import { clipPathAtWeek } from '../lib/curve'
import { passesOutcomeFilter } from '../lib/branchSummary'
import {
  buildSimulationMedian,
  buildSimulationTree,
  fanAxisMetric,
  forkWeekXs,
  TREE_ROOT_X,
  type FanAxisMode,
} from '../lib/simulationTree'
import { buildTimeTicks, formatVisibleSpan, weekAtTreeX } from '../lib/timeRuler'
import {
  TREE_AXIS_Y,
  TREE_BASE_Y,
  TREE_BRANCH_X,
  TREE_PLOT_TOP,
  TREE_TRUNK_X0,
  treeWeekX,
} from '../lib/trajectoryTree'
import { TimelineRail } from './TimelineRail'
import { TrunkRail } from './TrunkRail'

const TRUNK_MARKERS: IndicatorId[] = ['tsh', 'ft4', 'vitd', 'glucose', 'weight', 'activity']

/** Screen-stable radius — shrinks in world units as zoom increases. */
function FixedCircle({
  x,
  y,
  r,
  zoom,
  className,
  style,
  fill,
  stroke,
  strokeWidth,
  opacity,
}: {
  x: number
  y: number
  r: number
  zoom: number
  className?: string
  style?: React.CSSProperties
  fill?: string
  stroke?: string
  strokeWidth?: number
  opacity?: number
}) {
  const s = worldUiScale(zoom)
  return (
    <circle
      className={className}
      cx={x}
      cy={y}
      r={r * s}
      style={style}
      fill={fill}
      stroke={stroke}
      strokeWidth={strokeWidth !== undefined ? strokeWidth * s : undefined}
      opacity={opacity}
      vectorEffect="non-scaling-stroke"
    />
  )
}

function FixedText({
  x,
  y,
  zoom,
  className,
  textAnchor,
  opacity,
  style,
  children,
}: {
  x: number
  y: number
  zoom: number
  className?: string
  textAnchor?: 'start' | 'middle' | 'end' | 'inherit'
  opacity?: number
  style?: React.CSSProperties
  children: ReactNode
}) {
  const t = fixedLabelTransform(zoom, x, y)
  return (
    <text
      className={className}
      x={x}
      y={y}
      textAnchor={textAnchor}
      opacity={opacity}
      style={style}
      transform={t}
    >
      {children}
    </text>
  )
}

interface Props {
  result: RunResult
  baselines: Baselines
  subject: Subject
  protocol: AppliedIntervention[]
  indicatorId: IndicatorId
  fanAxisMode: FanAxisMode
  onFanAxisMode: (mode: FanAxisMode) => void
  cursorWeek: number
  simulationEndWeek: number
  simResetToken?: number
  selectedBranch: number | null
  showFavorable: boolean
  showUnfavorable: boolean
  onShowFavorable: (on: boolean) => void
  onShowUnfavorable: (on: boolean) => void
  onCursorChange: (week: number) => void
  onSelectBranch: (branch: number | null) => void
  onAddDrug: (spec: InterventionId) => void
  onDose: (key: string, dose: number) => void
  onStartWeek: (key: string, week: number) => void
  onRemoveDrug: (key: string) => void
}

export function EnsembleFan({
  result,
  baselines,
  subject,
  protocol,
  indicatorId,
  fanAxisMode,
  onFanAxisMode,
  cursorWeek,
  simulationEndWeek,
  simResetToken = 0,
  selectedBranch,
  showFavorable,
  showUnfavorable,
  onShowFavorable,
  onShowUnfavorable,
  onCursorChange,
  onSelectBranch,
  onAddDrug,
  onDose,
  onStartWeek,
  onRemoveDrug,
}: Props) {
  const { t, fmt, locale } = useI18n()
  const f = t.hero.figure
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [aspect, setAspect] = useState(16 / 9)

  const [fanView, setFanView] = useState<FanView>(() => defaultFanView(simulationEndWeek))

  const fanCtx = useMemo(
    () => ({ aspect, simulationEndWeek }),
    [aspect, simulationEndWeek],
  )
  const fanCtxRef = useRef(fanCtx)
  fanCtxRef.current = fanCtx

  useEffect(() => {
    setFanView(resetFanView(fanCtxRef.current))
  }, [simResetToken])

  useEffect(() => {
    setFanView((v) =>
      isFullTimelineVisible(v, fanCtx) ? fitFullTimelineView(v, fanCtx) : constrainFanView(v, fanCtx),
    )
  }, [fanCtx])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => {
      const { width, height } = el.getBoundingClientRect()
      if (height > 0) setAspect(width / height)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const metric = useMemo(
    () => fanAxisMetric(fanAxisMode, indicatorId, baselines, subject),
    [fanAxisMode, indicatorId, baselines, subject],
  )

  const visibleSpanWeeks = useMemo(
    () => visibleSpanLabel(fanCtx, fanView),
    [fanCtx, fanView],
  )

  const branchIndices = useMemo(
    () => Array.from({ length: result.count }, (_, i) => i),
    [result.count],
  )
  const branches = useMemo(
    () =>
      buildSimulationTree(
        result,
        cursorWeek,
        branchIndices,
        metric,
        fanView.spread,
        visibleSpanWeeks,
      ),
    [result, cursorWeek, branchIndices, metric, fanView.spread, visibleSpanWeeks],
  )
  const visibleBranches = useMemo(
    () =>
      branches
        .filter((br) => passesOutcomeFilter(br.outcome, showFavorable, showUnfavorable))
        .map((br) => ({
          ...br,
          midPts: clipPathAtWeek(br.midPts, cursorWeek, treeWeekX),
        })),
    [branches, cursorWeek, showFavorable, showUnfavorable],
  )
  const medianPts = useMemo(
    () => buildSimulationMedian(result, metric, fanView.spread, visibleSpanWeeks),
    [result, metric, fanView.spread, visibleSpanWeeks],
  )
  const visibleMedianPts = useMemo(
    () => clipPathAtWeek(medianPts, cursorWeek, treeWeekX),
    [medianPts, cursorWeek],
  )

  const bestBranchIndex = useMemo(
    () => pickBestBranch(result, baselines, subject),
    [result, baselines, subject],
  )

  const highlightedBestBranch = useMemo(() => {
    if (fanAxisMode === 'composite' || !showFavorable) return null
    const br = branches.find((b) => b.index === bestBranchIndex)
    if (!br || br.outcome !== 'improved') return null
    return bestBranchIndex
  }, [branches, bestBranchIndex, showFavorable, fanAxisMode])

  const trunkMarkers = useMemo(
    () =>
      TRUNK_MARKERS.map((id) => ({
        id,
        value: formatValue(id, baselines[id]),
        unit: INDICATOR_BY_ID[id].unit,
      })),
    [baselines],
  )

  const interventions = useMemo(
    () =>
      protocol
        .filter((iv) => iv.dose > 0 && iv.startWeek <= cursorWeek)
        .map((iv, i) => ({
          week: iv.startWeek,
          x: treeWeekX(iv.startWeek),
          name: t.engine.interventions[iv.spec].toUpperCase(),
          detail: fmt(t.ws.protocolStartLine, {
            week: iv.startWeek,
            dose: iv.dose,
            unit: t.engine.interventionUnits[iv.spec],
          }),
          color: ['var(--accent)', 'var(--branch-d)', 'var(--branch-c)', 'var(--branch-b)'][i % 4],
        })),
    [protocol, cursorWeek, t, fmt],
  )

  const fanExplainer =
    fanAxisMode === 'composite'
      ? fmt(t.ws.fanExplainerNormalized, {
          n: result.count,
          week: Math.round(cursorWeek * 2) / 2,
        })
      : fmt(t.ws.fanExplainer, {
          indicator: indicatorName(t, INDICATOR_BY_ID[indicatorId]),
          n: result.count,
          week: Math.round(cursorWeek * 2) / 2,
        })

  const cursorX = treeWeekX(cursorWeek)
  const zoom = fanView.zoom
  const visibleBox = useMemo(() => fanCameraRect(fanView, fanCtx), [fanView, fanCtx])
  const spanLabel = formatVisibleSpan(visibleSpanWeeks, locale)
  const atFullTimeline = isFullTimelineVisible(fanView, fanCtx)
  const atDayZoom = visibleSpanWeeks <= ZOOM_PRESET_DAY_WEEKS * 1.25
  const fitTimeline = () => setFanView((v) => fitFullTimelineView(v, fanCtx))
  const fitDay = () =>
    setFanView((v) => zoomToTimelineSpan(v, fanCtx, ZOOM_PRESET_DAY_WEEKS, cursorWeek))

  const timeTicks = useMemo(() => {
    const w0 = weekAtTreeX(visibleBox.x)
    const w1 = weekAtTreeX(visibleBox.x + visibleBox.w)
    return buildTimeTicks(w0, w1, locale, simulationEndWeek)
  }, [visibleBox, locale, simulationEndWeek])
  const viewBox = `${visibleBox.x} ${visibleBox.y} ${visibleBox.w} ${visibleBox.h}`
  const frameRight = visibleBox.x + visibleBox.w - 10
  const showRootDecor = isInViewX(TREE_ROOT_X, visibleBox, 48)
  const showYearCheckpoints = visibleSpanWeeks > 16
  const showProbCorner = zoom < 80
  const visibleInterventions = useMemo(
    () => interventions.filter((iv) => isInViewX(iv.x, visibleBox, treeWeekX(0.5))),
    [interventions, visibleBox],
  )

  const visibleCheckpoints = useMemo(() => {
    if (!showYearCheckpoints) return []
    const w0 = weekAtTreeX(visibleBox.x)
    const w1 = weekAtTreeX(visibleBox.x + visibleBox.w)
    return forkWeekXs().filter((w) => w >= w0 - 2 && w <= w1 + 2)
  }, [visibleBox, showYearCheckpoints])

  useEnsembleGl(containerRef, canvasRef, {
    branches: visibleBranches,
    medianPts: visibleMedianPts,
    fanView,
    fanCtx,
    selectedBranch,
    onSelectBranch,
    onFanView: setFanView,
    zoom,
    bestBranchIndex: highlightedBestBranch,
  })

  return (
    <div className="ensemble-tree figure-ltr" dir="ltr">
      <div className="ensemble-tree__chrome">
        <div className="ensemble-tree__zoom" role="group" aria-label={t.ws.zoomIn}>
          <button
            type="button"
            className="ensemble-tree__btn"
            onClick={() =>
              setFanView((v) =>
                constrainFanView(
                  { ...v, zoom: clampFanZoom(v.zoom / FAN_ZOOM_STEP, v.spread, aspect, simulationEndWeek) },
                  fanCtx,
                ),
              )
            }
            aria-label={t.ws.zoomOut}
            title={t.ws.zoomOut}
          >
            −
          </button>
          <button
            type="button"
            className="ensemble-tree__zoom-readout tabular"
            onClick={fitTimeline}
            title={t.ws.zoomSpanHint}
            aria-label={t.ws.zoomSpanHint}
          >
            {spanLabel}
          </button>
          <button
            type="button"
            className="ensemble-tree__btn"
            onClick={() =>
              setFanView((v) =>
                constrainFanView(
                  { ...v, zoom: clampFanZoom(v.zoom * FAN_ZOOM_STEP, v.spread, aspect, simulationEndWeek) },
                  fanCtx,
                ),
              )
            }
            aria-label={t.ws.zoomIn}
            title={t.ws.zoomIn}
          >
            +
          </button>
          <button
            type="button"
            className={`ensemble-tree__btn ensemble-tree__btn--text${atDayZoom ? ' ensemble-tree__btn--on' : ''}`}
            onClick={fitDay}
            title={t.ws.zoomDayHint}
          >
            {t.ws.zoomDay}
          </button>
          <button
            type="button"
            className={`ensemble-tree__btn ensemble-tree__btn--text${atFullTimeline ? ' ensemble-tree__btn--on' : ''}`}
            onClick={fitTimeline}
            title={t.ws.zoomFitAllHint}
          >
            {t.ws.zoomFitAll}
          </button>
        </div>
        <div className="ensemble-tree__filters" role="group" aria-label={t.ws.fanFilterLabel}>
          <label className="ensemble-tree__filter">
            <input
              type="checkbox"
              checked={showFavorable}
              onChange={(e) => onShowFavorable(e.target.checked)}
            />
            <span>{t.ws.fanFilterFavorable}</span>
          </label>
          <label className="ensemble-tree__filter">
            <input
              type="checkbox"
              checked={showUnfavorable}
              onChange={(e) => onShowUnfavorable(e.target.checked)}
            />
            <span>{t.ws.fanFilterUnfavorable}</span>
          </label>
          <label className="ensemble-tree__filter" title={t.ws.fanNormalizedHint}>
            <input
              type="checkbox"
              checked={fanAxisMode === 'composite'}
              onChange={(e) => onFanAxisMode(e.target.checked ? 'composite' : 'indicator')}
            />
            <span>{t.ws.fanNormalizedPanel}</span>
          </label>
          {fanAxisMode === 'indicator' && showFavorable && (
            <span className="ensemble-tree__legend-best mono-label" title={t.ws.fanBestBranchHint}>
              <span className="ensemble-tree__legend-swatch ensemble-tree__legend-swatch--best" />
              {t.ws.fanBestBranch}
            </span>
          )}
        </div>
      </div>
      <p className="ensemble-tree__explainer mono-label">{fanExplainer}</p>

      <div className="ensemble-tree__stage">
        <TrunkRail
          trunkMarkers={trunkMarkers}
          protocol={protocol}
          cursorWeek={cursorWeek}
          onAdd={onAddDrug}
          onDose={onDose}
          onStartWeek={onStartWeek}
          onRemove={onRemoveDrug}
        />

        <div className="ensemble-tree__main">
          <TimelineRail
            box={visibleBox}
            cursorWeek={cursorWeek}
            horizonWeeks={HORIZON_WEEKS}
            locale={locale}
            timeLabel={f.time.toUpperCase()}
            scrubLabel={t.ws.scrubLabel}
            onScrub={onCursorChange}
          />

          <div ref={containerRef} className="ensemble-tree__viewport ensemble-tree__viewport--gl">
            <div
              className="ensemble-tree__prob-corner"
              aria-hidden="true"
              data-zoomed={showProbCorner ? 'false' : 'true'}
            >
              {showProbCorner && (
                <>
                  <span className="ensemble-tree__prob-corner-mark" />
                  <span className="ensemble-tree__prob-corner-label mono-label">
                    {f.probability
                      .toUpperCase()
                      .split(' ')
                      .reduce<string[]>((lines, word, i, words) => {
                        const mid = Math.ceil(words.length / 2)
                        const line = i < mid ? 0 : 1
                        lines[line] = lines[line] ? `${lines[line]} ${word}` : word
                        return lines
                      }, [])
                      .filter(Boolean)
                      .map((line) => (
                        <span key={line}>{line}</span>
                      ))}
                  </span>
                </>
              )}
            </div>
            <canvas ref={canvasRef} className="ensemble-tree__gl" aria-hidden="true" />
            <svg
              className="trajectory-figure ensemble-tree__overlay"
              viewBox={viewBox}
              preserveAspectRatio="xMidYMid meet"
              role="img"
              aria-label={t.ws.ensembleTitle}
              pointerEvents="none"
            >
              <defs>
                <radialGradient id="ensemble-baseline-glow">
                  <stop offset="0%" stopOpacity="0.32" style={{ stopColor: 'var(--branch-a)' }} />
                  <stop offset="55%" stopOpacity="0.1" style={{ stopColor: 'var(--accent)' }} />
                  <stop offset="100%" stopOpacity="0" style={{ stopColor: 'var(--accent)' }} />
                </radialGradient>
              </defs>

              {zoom < 40 && (
                <g className="tf-frame">
                  {[
                    [TREE_TRUNK_X0 - 20, TREE_PLOT_TOP, 1, 1],
                    [TREE_TRUNK_X0 - 20, TREE_AXIS_Y, 1, -1],
                    [frameRight, TREE_AXIS_Y, -1, -1],
                  ].map(([cx, cy, sx, sy], i) => (
                    <path
                      key={i}
                      d={`M${cx} ${cy + sy * 14 * worldUiScale(zoom)}V${cy}H${cx + sx * 14 * worldUiScale(zoom)}`}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </g>
              )}

              {timeTicks.map((tick) => (
                <g key={`axis-${tick.week}-${tick.label}`} className="ensemble-tree__axis-tick">
                  <line
                    x1={treeWeekX(tick.week)}
                    y1={TREE_AXIS_Y - 6 * worldUiScale(zoom)}
                    x2={treeWeekX(tick.week)}
                    y2={TREE_AXIS_Y + 2 * worldUiScale(zoom)}
                    strokeWidth={1}
                    vectorEffect="non-scaling-stroke"
                    style={{ stroke: 'var(--line-soft)' }}
                    opacity={tick.major ? 0.9 : 0.55}
                  />
                  <FixedText
                    x={treeWeekX(tick.week)}
                    y={TREE_AXIS_Y + 16}
                    zoom={zoom}
                    className="tf-label"
                    textAnchor="middle"
                    opacity={tick.major ? 0.95 : 0.72}
                  >
                    {tick.label}
                  </FixedText>
                </g>
              ))}

              {visibleCheckpoints.map((week) => (
                <line
                  key={`cp${week}`}
                  className="tf-marker"
                  x1={treeWeekX(week)}
                  y1={TREE_PLOT_TOP + 8}
                  x2={treeWeekX(week)}
                  y2={TREE_AXIS_Y - 26}
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                  opacity={week > HORIZON_WEEKS ? 0.45 : 0.75}
                />
              ))}

              {showRootDecor && (
                <>
                  <line
                    className="ensemble-tree__trunk-line"
                    x1={TREE_ROOT_X}
                    y1={TREE_BASE_Y}
                    x2={TREE_BRANCH_X}
                    y2={TREE_BASE_Y}
                    strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke"
                    style={{ stroke: 'var(--accent-hi)' }}
                    opacity={0.85}
                  />

                  <FixedCircle
                    className="tf-glow"
                    x={TREE_ROOT_X}
                    y={TREE_BASE_Y}
                    r={28}
                    zoom={zoom}
                    fill="url(#ensemble-baseline-glow)"
                  />
                  <FixedCircle
                    className={zoom > 30 ? undefined : 'tf-pulse'}
                    x={TREE_ROOT_X}
                    y={TREE_BASE_Y}
                    r={5.5}
                    zoom={zoom}
                    style={{ fill: 'var(--trunk-hi)' }}
                  />

                  <g className="ensemble-tree__root">
                    <FixedText
                      x={TREE_ROOT_X}
                      y={TREE_BASE_Y - 30}
                      zoom={zoom}
                      className="tf-label"
                      textAnchor="middle"
                      style={{ fill: 'var(--trunk-ink)' }}
                    >
                      {t.ws.simulationRoot.toUpperCase()}
                    </FixedText>
                    <FixedText
                      x={TREE_ROOT_X}
                      y={TREE_BASE_Y - 18}
                      zoom={zoom}
                      className="tf-label"
                      textAnchor="middle"
                      opacity={0.7}
                    >
                      {fmt(t.ws.branchCountNote, { n: result.count })}
                    </FixedText>
                  </g>
                </>
              )}

              {visibleInterventions.map((iv, i) => (
                <g key={`${iv.week}-${i}`}>
                  <line
                    x1={iv.x}
                    y1={TREE_PLOT_TOP + 40 * worldUiScale(zoom)}
                    x2={iv.x}
                    y2={TREE_AXIS_Y - 8}
                    strokeWidth={1}
                    vectorEffect="non-scaling-stroke"
                    style={{ stroke: iv.color }}
                  />
                  <FixedCircle
                    x={iv.x}
                    y={TREE_PLOT_TOP + 40 * worldUiScale(zoom)}
                    r={4.6}
                    zoom={zoom}
                    stroke={iv.color}
                    strokeWidth={1.4}
                    style={{ fill: 'var(--bg-raise)' }}
                  />
                  <FixedText
                    x={iv.x - 12 * worldUiScale(zoom)}
                    y={TREE_PLOT_TOP + 24 * worldUiScale(zoom)}
                    zoom={zoom}
                    className="tf-label"
                    textAnchor="end"
                    style={{ fill: 'var(--trunk-ink)' }}
                  >
                    {iv.name}
                  </FixedText>
                  <FixedText
                    x={iv.x - 12 * worldUiScale(zoom)}
                    y={TREE_PLOT_TOP + 36 * worldUiScale(zoom)}
                    zoom={zoom}
                    className="tf-label"
                    textAnchor="end"
                    opacity={0.75}
                  >
                    {iv.detail}
                  </FixedText>
                </g>
              ))}

              {isInViewX(cursorX, visibleBox, treeWeekX(0.25)) && (
                <>
                  <line
                    className="tf-marker"
                    x1={cursorX}
                    y1={TREE_PLOT_TOP}
                    x2={cursorX}
                    y2={TREE_AXIS_Y - 8}
                    strokeWidth={1}
                    vectorEffect="non-scaling-stroke"
                    opacity={0.9}
                  />
                  <FixedCircle
                    className={zoom > 30 ? undefined : 'tf-node'}
                    x={cursorX}
                    y={TREE_BASE_Y}
                    r={4}
                    zoom={zoom}
                    style={{ fill: 'var(--bg-raise)', stroke: 'var(--accent)' }}
                    strokeWidth={1.3}
                  />
                </>
              )}
            </svg>
          </div>
        </div>
      </div>
    </div>
  )
}
