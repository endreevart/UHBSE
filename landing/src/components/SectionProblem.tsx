import { useI18n } from '../i18n'
import { Reveal } from './Reveal'

export function SectionProblem() {
  const { t } = useI18n()
  const items = [t.problem.p1, t.problem.p2, t.problem.p3, t.problem.p4]

  return (
    <section className="section" id="research">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.problem.kicker}</p>
          <h2 className="display display--l">{t.problem.title}</h2>
        </Reveal>

        <div className="problem__body">
          {items.map((text, i) => (
            <Reveal key={i} className="problem__item" delay={i * 90}>
              <span className="mono-label problem__index tabular">
                {String(i + 1).padStart(2, '0')}
              </span>
              <p className="body-text">{text}</p>
            </Reveal>
          ))}
        </div>

        <Reveal delay={120}>
          <p className="problem__closing">{t.problem.closing}</p>
        </Reveal>
      </div>
    </section>
  )
}
