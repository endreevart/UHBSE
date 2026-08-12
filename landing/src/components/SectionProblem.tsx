import { useI18n } from '../i18n'
import { Reveal } from './Reveal'
import { SectionHead } from './SectionHead'

export function SectionProblem() {
  const { t } = useI18n()
  const items = [t.problem.p1, t.problem.p2, t.problem.p3, t.problem.p4]

  return (
    <section className="section" id="research" aria-labelledby="research-heading">
      <div className="shell">
        <SectionHead
          headingId="research-heading"
          title={t.problem.title}
        />

        <ol className="problem__body">
          {items.map((text, i) => (
            <Reveal as="li" key={i} className="problem__item" delay={i * 90}>
              <span className="mono-label problem__index tabular" aria-hidden="true">
                {String(i + 1).padStart(2, '0')}
              </span>
              <p className="body-text">{text}</p>
            </Reveal>
          ))}
        </ol>

        <Reveal delay={120}>
          <p className="problem__closing">{t.problem.closing}</p>
        </Reveal>
      </div>
    </section>
  )
}
