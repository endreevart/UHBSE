import { useI18n } from '../i18n'
import { Reveal } from './Reveal'
import { SectionHead } from './SectionHead'

export function SectionImpact() {
  const { t } = useI18n()

  return (
    <section className="section" id="impact" aria-labelledby="impact-heading">
      <div className="shell">
        <SectionHead headingId="impact-heading" title={t.impact.title} />

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
