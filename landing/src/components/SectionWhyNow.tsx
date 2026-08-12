import { useI18n } from '../i18n'
import { Reveal } from './Reveal'
import { SectionHead } from './SectionHead'

export function SectionWhyNow() {
  const { t } = useI18n()

  return (
    <section className="section" id="why-now" aria-labelledby="why-now-heading">
      <div className="shell">
        <SectionHead headingId="why-now-heading" title={t.whyNow.title} />

        <div className="why">
          {t.whyNow.conditions.map((c, i) => (
            <Reveal className="why__item" key={c.index} delay={i * 120}>
              <span className="why__index tabular" aria-hidden="true">
                {c.index}
              </span>
              <h3 className="why__title">{c.title}</h3>
              <p className="why__text">{c.text}</p>
            </Reveal>
          ))}
        </div>

        <Reveal className="why__closing" delay={120}>
          <p>{t.whyNow.closingA}</p>
          <p>{t.whyNow.closingB}</p>
        </Reveal>
      </div>
    </section>
  )
}
