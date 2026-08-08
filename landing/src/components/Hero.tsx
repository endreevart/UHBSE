import { useI18n } from '../i18n'
import { HeroFigure } from './HeroFigure'
import { Reveal } from './Reveal'
import { TrajectoryInstrumentLegend } from './TrajectoryInstrumentLegend'

export function Hero() {
  const { t } = useI18n()

  return (
    <section className="hero" id="top">
      <div className="shell">
        <div className="hero__grid">
          <div className="hero__col">
            <Reveal>
              <h1 className="display display--xl hero__title">
                <span>{t.hero.titleA}</span>
                <span className="hero__title-b">{t.hero.titleB}</span>
              </h1>
            </Reveal>
          </div>

          <div className="hero__col hero__col--aside">
            <Reveal delay={120}>
              <p className="lede hero__lead">{t.hero.lead}</p>
            </Reveal>

            <Reveal delay={200}>
              <p className="hero__sub">{t.hero.sub}</p>
            </Reveal>

            <Reveal delay={280}>
              <div className="hero__actions">
                <a className="btn btn--primary" href="#engine">
                  {t.hero.ctaPrimary}
                  <span className="btn__arrow" aria-hidden="true">
                    →
                  </span>
                </a>
                <a className="btn btn--ghost" href="#research">
                  {t.hero.ctaSecondary}
                  <span className="btn__arrow" aria-hidden="true">
                    →
                  </span>
                </a>
              </div>
            </Reveal>
          </div>
        </div>

        <Reveal className="rig plate" delay={200}>
          <div className="rig__bar">
            <span className="rig__id">{t.hero.figure.panel}</span>
            <span className="rig__meta">
              {[
                [t.hero.figure.subject, 'S-0417'],
                [t.hero.figure.horizon, `36 ${t.engine.weekShort}`],
                [t.hero.figure.branches, '4'],
                [t.hero.figure.step, `0.5 ${t.engine.weekShort}`],
              ].map(([label, value]) => (
                <span className="rig__stat" key={label}>
                  <i>{label}</i>
                  <b>{value}</b>
                </span>
              ))}
            </span>
          </div>

          <div className="rig__body">
            <HeroFigure />
          </div>

          <div className="rig__foot">
            <TrajectoryInstrumentLegend />
            <span className="rig__note">{t.engine.disclaimer}</span>
          </div>
        </Reveal>
      </div>
    </section>
  )
}
