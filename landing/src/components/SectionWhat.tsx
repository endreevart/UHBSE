import { useI18n } from '../i18n'
import { useScrollProgress } from '../lib/useInView'
import { Reveal } from './Reveal'

export function SectionWhat() {
  const { t } = useI18n()
  const { ref, progress } = useScrollProgress<HTMLDivElement>()
  const activeIndex = Math.min(t.what.flow.length - 1, Math.floor(progress * t.what.flow.length))

  return (
    <section className="section">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.what.kicker}</p>
          <h2 className="display display--l">{t.what.title}</h2>
          <p className="lede">{t.what.lead}</p>
        </Reveal>

        <div ref={ref}>
          <div className="flow">
            {t.what.flow.map((step, i) => (
              <div className="flow__step" key={step.label} data-active={i <= activeIndex}>
                <div className="flow__node">
                  <span
                    className="flow__dot"
                    style={{
                      opacity: i <= activeIndex ? 1 : 0.25,
                      transition: 'opacity .5s var(--ease)',
                    }}
                  />
                  <span className="flow__num tabular">{String(i + 1).padStart(2, '0')}</span>
                </div>
                <h3 className="flow__label">{step.label}</h3>
                <p className="flow__caption">{step.caption}</p>
              </div>
            ))}
          </div>
          <div
            className="flow__rail"
            style={{ ['--progress' as string]: String(Math.max(0.04, progress)) }}
            aria-hidden="true"
          />
        </div>

        <Reveal delay={120}>
          <p className="body-text" style={{ marginBlockStart: 34 }}>
            {t.what.sub}
          </p>
        </Reveal>
      </div>
    </section>
  )
}
