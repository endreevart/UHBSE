import { useI18n } from '../i18n'
import { Reveal } from './Reveal'

export function SectionStatus() {
  const { t } = useI18n()

  return (
    <section className="section">
      <div className="shell status">
        <Reveal>
          <p className="kicker" style={{ marginBlockEnd: 22 }}>
            {t.status.kicker}
          </p>
          <h2 className="display display--m" style={{ marginBlockEnd: 20 }}>
            {t.status.title}
          </h2>
          <p className="body-text">{t.status.lead}</p>
          <div className="status__note">{t.status.dataNote}</div>
        </Reveal>

        <Reveal delay={120}>
          <ul className="status__list">
            {t.status.items.map((item) => (
              <li key={item}>
                <span className="status__tick" aria-hidden="true" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </section>
  )
}
