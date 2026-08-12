import { useI18n } from '../i18n'
import { Reveal } from './Reveal'
import { SectionHead } from './SectionHead'

export function SectionPrinciples() {
  const { t } = useI18n()

  return (
    <section className="section" id="principles" aria-labelledby="principles-heading">
      <div className="shell">
        <SectionHead
          headingId="principles-heading"
          title={t.trust.title}
        />

        <ol className="problem__body">
          {t.trust.principles.map((text, i) => (
            <Reveal as="li" key={text} className="problem__item" delay={i * 90}>
              <span className="mono-label problem__index tabular" aria-hidden="true">
                {String(i + 1).padStart(2, '0')}
              </span>
              <h3 className="body-text problem__heading">{text}</h3>
            </Reveal>
          ))}
        </ol>

        <Reveal delay={120}>
          <p className="problem__closing">{t.trust.lead}</p>
        </Reveal>
      </div>
    </section>
  )
}
