import { useI18n } from '../i18n'
import { Reveal } from './Reveal'

export function SectionWhyNow() {
  const { t } = useI18n()

  return (
    <section className="section">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.whyNow.kicker}</p>
          <h2 className="display display--l">{t.whyNow.title}</h2>
        </Reveal>

        <div className="why">
          {t.whyNow.conditions.map((c, i) => (
            <Reveal className="why__item" key={c.index} delay={i * 120}>
              <span className="why__index tabular">{c.index}</span>
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
