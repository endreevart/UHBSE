import { useI18n } from '../i18n'
import { Reveal } from './Reveal'

export function SectionPrinciples() {
  const { t } = useI18n()

  return (
    <section className="section" id="principles">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.trust.kicker}</p>
          <h2 className="display display--l">{t.trust.title}</h2>
        </Reveal>

        <div className="problem__body">
          {t.trust.principles.map((text, i) => (
            <Reveal key={text} className="problem__item" delay={i * 90}>
              <span className="mono-label problem__index tabular">
                {String(i + 1).padStart(2, '0')}
              </span>
              <p className="body-text">{text}</p>
            </Reveal>
          ))}
        </div>

        <Reveal delay={120}>
          <p className="problem__closing">{t.trust.lead}</p>
        </Reveal>
      </div>
    </section>
  )
}
