import { useI18n } from '../i18n'
import { Reveal } from './Reveal'

export function SectionImpact() {
  const { t } = useI18n()

  return (
    <section className="section">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.impact.kicker}</p>
          <h2 className="display display--l">{t.impact.title}</h2>
        </Reveal>

        <div className="impact">
          {t.impact.groups.map((group, i) => (
            <Reveal className="impact__col" key={group.title} delay={i * 110}>
              <h3 className="impact__title">{group.title}</h3>
              {group.note ? <span className="impact__note">{group.note}</span> : <div style={{ height: 24 }} />}
              <ul className="impact__list">
                {group.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}
