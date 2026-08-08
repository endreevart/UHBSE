import { useMemo } from 'react'
import { useI18n } from '../i18n'
import { sampleBranch, toBand, toPath } from '../lib/curve'

/* Wide instrument aspect: the figure runs the full width of the shell, so the
   trunk gets room for the observed panel and the fan gets room to separate. */
const W = 1440
const H = 460
const BASE_Y = 250
const TRUNK_X0 = 64
const BRANCH_X = 616
const END_X = 1236
const AXIS_Y = 420
const PLOT_TOP = 78
const PX_PER_WEEK = (END_X - BRANCH_X) / 36

const weekX = (week: number) => BRANCH_X + week * PX_PER_WEEK

/** Observed profile ticks on the trunk, staggered so labels never collide. */
const MARKERS = [
  { id: 'tsh', name: 'TSH', value: '1.82', unit: 'mIU/L', x: 145, row: 0 },
  { id: 'ft4', name: 'FT4', value: '1.24', unit: 'ng/dL', x: 238, row: 1 },
  { id: 'vitd', name: 'Vitamin D', value: '32', unit: 'ng/mL', x: 332, row: 0 },
  { id: 'glu', name: 'glucose', value: '92', unit: 'mg/dL', x: 426, row: 1 },
  { id: 'wt', name: 'weight', value: '72.4', unit: 'kg', x: 519, row: 0 },
  {
    id: 'act',
    name: 'activity',
    value: '7 840',
    unit: 'steps',
    x: 603,
    row: 1,
  },
]

const ROW_OFFSET = [24, 76]

/**
 * Trunk and branches share one linear cycle, so the trunk pulse reaches the fork
 * exactly as the branch pulses leave it. Every delay below is a phase of that cycle.
 */
const FLOW_CYCLE = 5
const phase = (from: number, at: number, to: number) => ((at - from) / (to - from)) * FLOW_CYCLE

interface Branch {
  id: string
  color: string
  fromX: number
  fromY: number
  endY: number
  spread: number
  delay: number
}

const BRANCHES: Branch[] = [
  {
    id: 'a',
    color: 'var(--branch-a)',
    fromX: BRANCH_X,
    fromY: BASE_Y,
    endY: 144,
    spread: 28,
    delay: 0.1,
  },
  {
    id: 'b',
    color: 'var(--branch-b)',
    fromX: BRANCH_X,
    fromY: BASE_Y,
    endY: 210,
    spread: 24,
    delay: 0.28,
  },
  {
    id: 'c',
    color: 'var(--branch-c)',
    fromX: BRANCH_X,
    fromY: BASE_Y,
    endY: 288,
    spread: 22,
    delay: 0.46,
  },
  {
    id: 'd',
    color: 'var(--branch-d)',
    fromX: weekX(11),
    fromY: 278,
    endY: 362,
    spread: 24,
    delay: 0.72,
  },
]

function bandPaths(branch: Branch) {
  const mid = sampleBranch(branch.fromX, branch.fromY, END_X, branch.endY, 56)
  const span = END_X - branch.fromX
  const widen = (p: { x: number; y: number }, sign: number) => ({
    x: p.x,
    y: p.y + sign * branch.spread * Math.pow((p.x - branch.fromX) / span, 1.35),
  })
  const outerUp = mid.map((p) => widen(p, -1))
  const outerDown = mid.map((p) => widen(p, 1))
  const innerUp = mid.map((p) => widen(p, -0.42))
  const innerDown = mid.map((p) => widen(p, 0.42))
  return {
    mid: toPath(mid),
    outer: toBand(outerUp, outerDown),
    inner: toBand(innerUp, innerDown),
    upper: toPath(outerUp),
    lower: toPath(outerDown),
  }
}

export function HeroFigure() {
  const { t, fmt } = useI18n()
  const f = t.hero.figure
  const branches = useMemo(() => BRANCHES.map((b) => ({ b, paths: bandPaths(b) })), [])

  return (
    <div className="figure-ltr" dir="ltr">
      <svg
        className="trajectory-figure"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={t.hero.lead}
      >
        <defs>
          {/* a halo, not a lamp: enough to mark where the trunk starts without
              the bloom that makes a chart look like a screensaver */}
          <radialGradient id="baselineGlow">
            <stop offset="0%" stopOpacity="0.32" style={{ stopColor: 'var(--branch-a)' }} />
            <stop offset="55%" stopOpacity="0.1" style={{ stopColor: 'var(--accent)' }} />
            <stop offset="100%" stopOpacity="0" style={{ stopColor: 'var(--accent)' }} />
          </radialGradient>
          {/* userSpaceOnUse: the trunk is a zero-height bbox, so an objectBoundingBox
            gradient would collapse and the line would not paint at all */}
          <linearGradient
            id="trunkLine"
            gradientUnits="userSpaceOnUse"
            x1={TRUNK_X0}
            y1={BASE_Y}
            x2={BRANCH_X}
            y2={BASE_Y}
          >
            <stop offset="0%" stopOpacity="0.15" style={{ stopColor: 'var(--accent)' }} />
            <stop offset="18%" stopOpacity="0.95" style={{ stopColor: 'var(--accent-hi)' }} />
            <stop offset="100%" stopOpacity="1" style={{ stopColor: 'var(--branch-a)' }} />
          </linearGradient>
          {BRANCHES.map((b) => (
            <linearGradient key={b.id} id={`band-${b.id}`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopOpacity="0" style={{ stopColor: b.color }} />
              <stop offset="100%" stopOpacity="0.55" style={{ stopColor: b.color }} />
            </linearGradient>
          ))}
        </defs>

        {/* coordinate grid: horizontals across the whole plate, verticals only in
          the projected half, where time is a quantity rather than a record */}
        <g className="tf-grid">
          {Array.from({ length: 9 }, (_, i) => PLOT_TOP + i * 42).map((y) => (
            <line key={`h${y}`} x1={TRUNK_X0 - 20} y1={y} x2={END_X + 10} y2={y} />
          ))}
          {Array.from({ length: 13 }, (_, i) => weekX(i * 3)).map((x, i) => (
            <line key={`v${i}`} x1={x} y1={PLOT_TOP} x2={x} y2={AXIS_Y - 8} />
          ))}
        </g>

        {/* registration corners: the plate is a measured frame, not a picture */}
        <g className="tf-frame">
          {[
            [TRUNK_X0 - 20, PLOT_TOP, 1, 1],
            [END_X + 10, PLOT_TOP, -1, 1],
            [TRUNK_X0 - 20, AXIS_Y, 1, -1],
            [END_X + 10, AXIS_Y, -1, -1],
          ].map(([cx, cy, sx, sy], i) => (
            <path key={i} d={`M${cx} ${cy + sy * 14}V${cy}H${cx + sx * 14}`} />
          ))}
        </g>

        {/* uncertainty ribbons */}
        {branches.map(({ b, paths }) => (
          <g key={`band-${b.id}`} className="tf-breathe" style={{ animationDelay: `${b.delay}s` }}>
            <path d={paths.outer} fill={`url(#band-${b.id})`} opacity="0.13" />
            <path d={paths.inner} fill={`url(#band-${b.id})`} opacity="0.16" />
            <path
              className="tf-path tf-draw"
              d={paths.upper}
              strokeOpacity="0.42"
              strokeWidth="0.7"
              strokeDasharray="3 4"
              style={{
                stroke: b.color,
                ['--len' as string]: '900',
                animationDelay: `${b.delay + 0.3}s`,
              }}
            />
            <path
              className="tf-path tf-draw"
              d={paths.lower}
              strokeOpacity="0.42"
              strokeWidth="0.7"
              strokeDasharray="3 4"
              style={{
                stroke: b.color,
                ['--len' as string]: '900',
                animationDelay: `${b.delay + 0.3}s`,
              }}
            />
          </g>
        ))}

        {/* checkpoints */}
        {/* labels are staggered so long translations never collide */}
        {[12, 24].map((week, i) => {
          const top = i === 0 ? 92 : 124
          return (
            <g key={`cp${week}`}>
              <line
                className="tf-marker"
                x1={weekX(week)}
                y1={top + 22}
                x2={weekX(week)}
                y2={AXIS_Y - 26}
              />
              <text className="tf-label" x={weekX(week)} y={top} textAnchor="middle">
                {f.checkpoint}
              </text>
              <text
                className="tf-label"
                x={weekX(week)}
                y={top + 12}
                textAnchor="middle"
                opacity="0.7"
              >
                {fmt(f.week, { n: week })}
              </text>
              <path
                d={`M${weekX(week) - 4} ${top + 18} L${weekX(week) + 4} ${top + 18} L${weekX(week)} ${top + 24} Z`}
                style={{ fill: 'var(--ink-ghost)' }}
              />
            </g>
          )
        })}

        {/* median trajectories */}
        {branches.map(({ b, paths }) => (
          <path
            key={`mid-${b.id}`}
            className="tf-path tf-draw"
            d={paths.mid}
            style={{
              stroke: b.color,
              ['--len' as string]: '900',
              animationDelay: `${b.delay}s`,
            }}
          />
        ))}

        {/* travelling pulses: each branch carries the baseline signal outward */}
        {branches.map(({ b, paths }) => (
          <path
            key={`flow-${b.id}`}
            className="tf-flow"
            d={paths.mid}
            pathLength={100}
            style={{ stroke: b.color, animationDelay: `${b.delay * 0.16}s` }}
          />
        ))}

        {/* checkpoint state dots */}
        {branches.map(({ b }) => {
          const pts = sampleBranch(b.fromX, b.fromY, END_X, b.endY, 200)
          return [12, 24].map((week) => {
            const x = weekX(week)
            if (x < b.fromX) return null
            const p = pts.reduce((best, cur) =>
              Math.abs(cur.x - x) < Math.abs(best.x - x) ? cur : best,
            )
            return (
              <circle
                key={`${b.id}-${week}`}
                className="tf-node"
                cx={p.x}
                cy={p.y}
                r={3.4}
                strokeWidth="1.3"
                style={{
                  fill: 'var(--bg-raise)',
                  stroke: b.color,
                  animationDelay: `${phase(b.fromX, x, END_X)}s`,
                }}
              />
            )
          })
        })}

        {/* probability ladders */}
        {branches.map(({ b }) => (
          <g key={`prob-${b.id}`}>
            {[
              { label: '90%', dy: -20 },
              { label: '50%', dy: 0 },
              { label: '10%', dy: 20 },
            ].map((p) => (
              <text
                key={p.label}
                className="tf-label"
                x={END_X + 14}
                y={b.endY + p.dy + 3}
                opacity={p.dy === 0 ? 0.95 : 0.5}
              >
                {p.label}
              </text>
            ))}
          </g>
        ))}
        {(() => {
          const words = f.probability.split(' ')
          const cut = Math.ceil(words.length / 2)
          return [words.slice(0, cut).join(' '), words.slice(cut).join(' ')].map((line, i) =>
            line ? (
              <text
                key={i}
                className="tf-label"
                x={END_X + 14}
                y={102 + i * 12}
                opacity="0.8"
                style={{ fontSize: 9 }}
              >
                {line}
              </text>
            ) : null,
          )
        })()}

        {/* trunk: observed history */}
        <line
          x1={TRUNK_X0}
          y1={BASE_Y}
          x2={BRANCH_X}
          y2={BASE_Y}
          stroke="url(#trunkLine)"
          strokeWidth="1.6"
        />
        <line
          className="tf-flow tf-flow--trunk"
          x1={TRUNK_X0}
          y1={BASE_Y}
          x2={BRANCH_X}
          y2={BASE_Y}
          pathLength={100}
          style={{ stroke: 'var(--trunk-hi)' }}
        />
        <circle
          className="tf-glow"
          cx={TRUNK_X0 + 8}
          cy={BASE_Y}
          r="26"
          fill="url(#baselineGlow)"
        />
        <circle
          className="tf-pulse"
          cx={TRUNK_X0 + 8}
          cy={BASE_Y}
          r="4"
          style={{ fill: 'var(--trunk-hi)' }}
        />

        <text
          className="tf-label"
          x={TRUNK_X0}
          y={BASE_Y - 18}
          style={{ fill: 'var(--trunk-ink)' }}
        >
          {f.baseline.toUpperCase()}
        </text>

        {MARKERS.map((m) => {
          const top = BASE_Y + ROW_OFFSET[m.row]
          const lit = phase(TRUNK_X0, m.x, BRANCH_X)
          return (
            <g key={m.id}>
              <circle
                className="tf-tick"
                cx={m.x}
                cy={BASE_Y}
                r="3.4"
                strokeWidth="1.2"
                style={{
                  fill: 'var(--bg-raise)',
                  stroke: 'var(--accent-hi)',
                  animationDelay: `${lit}s`,
                }}
              />
              <line
                x1={m.x}
                y1={BASE_Y + 5}
                x2={m.x}
                y2={top - 12}
                strokeWidth="1"
                style={{ stroke: 'rgba(var(--accent-rgb), 0.34)' }}
              />
              <text className="tf-label" x={m.x} y={top} textAnchor="middle">
                {m.name}
              </text>
              <text className="tf-value" x={m.x} y={top + 16} textAnchor="middle">
                {m.value}
              </text>
              <text className="tf-label" x={m.x} y={top + 29} textAnchor="middle" opacity="0.55">
                {m.unit}
              </text>
            </g>
          )
        })}

        {/* intervention A */}
        <g>
          <line
            x1={BRANCH_X}
            y1={174}
            x2={BRANCH_X}
            y2={BASE_Y}
            strokeWidth="1.2"
            style={{ stroke: 'var(--accent)' }}
          />
          <circle
            cx={BRANCH_X}
            cy={174}
            r="4.6"
            strokeWidth="1.4"
            style={{ fill: 'var(--bg-raise)', stroke: 'var(--accent)' }}
          />
          <text
            className="tf-label"
            x={BRANCH_X - 12}
            y={154}
            textAnchor="end"
            style={{ fill: 'var(--trunk-ink)' }}
          >
            {f.interventionA.toUpperCase()}
          </text>
          <text className="tf-label" x={BRANCH_X - 12} y={166} textAnchor="end" opacity="0.75">
            {f.interventionADetail}
          </text>
        </g>

        {/* intervention B */}
        <g>
          <line
            x1={weekX(11)}
            y1={278}
            x2={weekX(11)}
            y2={368}
            strokeWidth="1.2"
            style={{ stroke: 'var(--branch-d)' }}
          />
          <circle
            cx={weekX(11)}
            cy={368}
            r="4.6"
            strokeWidth="1.4"
            style={{ fill: 'var(--bg-raise)', stroke: 'var(--branch-d)' }}
          />
          <text
            className="tf-label"
            x={weekX(11) - 10}
            y={386}
            textAnchor="end"
            style={{ fill: 'var(--branch-d-ink)' }}
          >
            {f.interventionB.toUpperCase()}
          </text>
          <text className="tf-label" x={weekX(11) - 10} y={398} textAnchor="end" opacity="0.75">
            {f.interventionBDetail}
          </text>
        </g>

        {/* time axis: a tick every week, labelled every sixth, so the horizon reads
          as a measured scale rather than four round numbers */}
        <line className="tf-axis" x1={TRUNK_X0 - 20} y1={AXIS_Y} x2={END_X + 10} y2={AXIS_Y} />
        <text className="tf-label" x={TRUNK_X0 - 20} y={AXIS_Y - 12}>
          {f.time.toUpperCase()}
        </text>
        <g className="tf-ticks">
          {Array.from({ length: 37 }, (_, week) => week).map((week) => (
            <line
              key={`tick${week}`}
              x1={weekX(week)}
              y1={AXIS_Y}
              x2={weekX(week)}
              y2={AXIS_Y + (week % 6 === 0 ? 8 : 4)}
              opacity={week % 6 === 0 ? 0.75 : 0.4}
            />
          ))}
        </g>
        {[0, 6, 12, 18, 24, 30, 36].map((week) => (
          <text
            key={`tickl${week}`}
            className="tf-value"
            x={weekX(week)}
            y={AXIS_Y + 22}
            textAnchor="middle"
            opacity="0.55"
          >
            {week}
          </text>
        ))}
      </svg>
    </div>
  )
}
