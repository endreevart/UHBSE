import { useI18n } from '../i18n'
import { smoothPath, toBand } from '../lib/curve'
import { Reveal } from './Reveal'

const W = 1400
const H = 120
const MID = H / 2
const DOTS = 24
const STEPS = 64

function jitter(seed: number, i: number, amp: number) {
  return (Math.sin(i * 1.9 + seed * 2.3) * 0.6 + Math.sin(i * 4.1 + seed * 5.1) * 0.4) * amp
}

/** Shared loop length; each layer animates a different aspect of the same cycle. */
const CYCLE = 6

/** Evidence: measurements are read off in order, so the points light up in sequence. */
function ObservedPlot({ color }: { color: string }) {
  const dots = Array.from({ length: DOTS }, (_, i) => ({
    x: 14 + (i * (W - 30)) / (DOTS - 1),
    y: MID + jitter(1, i, 20),
    err: 11 + Math.abs(jitter(3, i, 9)),
    at: (i / (DOTS - 1)) * CYCLE,
  }))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} aria-hidden="true" style={{ color }}>
      {dots.map((d, i) => (
        <g key={i} style={{ animationDelay: `${d.at}s` }}>
          <line
            className="ly-err"
            x1={d.x}
            y1={d.y - d.err}
            x2={d.x}
            y2={d.y + d.err}
            stroke="currentColor"
            style={{ animationDelay: `${d.at}s` }}
          />
          <circle
            className="ly-dot"
            cx={d.x}
            cy={d.y}
            r="3.6"
            fill="currentColor"
            style={{ animationDelay: `${d.at}s` }}
          />
        </g>
      ))}
    </svg>
  )
}

/** Simulation: one hypothesis being computed, so a pulse runs the length of it. */
function ScenarioPlot({ color }: { color: string }) {
  const pts = Array.from({ length: STEPS }, (_, i) => ({
    x: 14 + (i * (W - 30)) / (STEPS - 1),
    y: MID + jitter(7, i * 0.32, 18),
  }))
  const up = pts.map((p, i) => ({ x: p.x, y: p.y - 11 - i * 0.2 }))
  const down = pts.map((p, i) => ({ x: p.x, y: p.y + 11 + i * 0.2 }))
  const mid = smoothPath(pts)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} aria-hidden="true" style={{ color }}>
      <path className="ly-band" d={toBand(up, down)} fill="currentColor" />
      <path
        d={smoothPath(up)}
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.45"
        strokeWidth="0.9"
        strokeDasharray="3 4"
      />
      <path
        d={smoothPath(down)}
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.45"
        strokeWidth="0.9"
        strokeDasharray="3 4"
      />
      <path d={mid} fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path className="ly-flow" d={mid} pathLength={100} stroke="currentColor" />
    </svg>
  )
}

/** Prediction: several futures drawn from one present, so the pulses fan out. */
function PredictedPlot({ color }: { color: string }) {
  const branches = [-42, -15, 13, 40]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} aria-hidden="true" style={{ color }}>
      {branches.map((offset, b) => {
        const pts = Array.from({ length: STEPS }, (_, i) => {
          const k = i / (STEPS - 1)
          return {
            x: 14 + (i * (W - 30)) / (STEPS - 1),
            y: MID + offset * Math.pow(k, 1.5) + jitter(b + 2, i * 0.4, 6) * k,
          }
        })
        const up = pts.map((p, i) => ({ x: p.x, y: p.y - (i / (STEPS - 1)) * 13 }))
        const down = pts.map((p, i) => ({ x: p.x, y: p.y + (i / (STEPS - 1)) * 13 }))
        const line = smoothPath(pts)
        return (
          <g key={b}>
            <path
              className="ly-band ly-band--faint"
              d={toBand(up, down)}
              fill="currentColor"
              style={{ animationDelay: `${b * 0.6}s` }}
            />
            <path d={line} fill="none" stroke="currentColor" strokeWidth="1.2" opacity="0.85" />
            <path
              className="ly-flow"
              d={line}
              pathLength={100}
              stroke="currentColor"
              style={{ animationDelay: `${b * 0.32}s` }}
            />
          </g>
        )
      })}
    </svg>
  )
}

export function SectionLayers() {
  const { t } = useI18n()

  const rows = [
    { key: 'observed', color: 'var(--control)', data: t.layers.observed, Plot: ObservedPlot },
    { key: 'scenario', color: 'var(--branch-b)', data: t.layers.scenario, Plot: ScenarioPlot },
    { key: 'predicted', color: 'var(--branch-d-ink)', data: t.layers.predicted, Plot: PredictedPlot },
  ]

  return (
    <section className="section">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.layers.kicker}</p>
          <h2 className="display display--l">{t.layers.title}</h2>
          <p className="lede">{t.layers.lead}</p>
        </Reveal>

        <div className="layers">
          {rows.map(({ key, color, data, Plot }, i) => (
            <div className="layers__row" key={key}>
              <Reveal className="layers__meta" delay={i * 100}>
                <h3 className="layers__title">
                  <span className="layers__bullet" style={{ background: color }} />
                  {data.title}
                </h3>
                <p className="layers__text">{data.text}</p>
              </Reveal>
              <Reveal className="layers__plot" delay={i * 100 + 60}>
                <Plot color={color} />
              </Reveal>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
