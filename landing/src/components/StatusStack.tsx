import { useI18n } from '../i18n'
import { Reveal } from './Reveal'

export function StatusStack({ headingId }: { headingId: string }) {
  const { t } = useI18n()
  let step = 0

  return (
    <div className="roadmap">
      <Reveal className="roadmap__head roadmap__reveal">
        <header>
          <h2 id={headingId} className="display display--m roadmap__title">
            {t.status.title}
          </h2>
          <p className="body-text roadmap__lead">{t.status.lead}</p>
        </header>
      </Reveal>

      <div className="roadmap__timeline">
        <div className="roadmap__rail" aria-hidden />

        {t.status.sections.map((section) => {
          const phaseDelay = step++ * 70

          return (
            <section key={section.id} className="roadmap__phase" data-phase={section.id}>
              <Reveal
                className="roadmap__phase-head roadmap__reveal roadmap__reveal--phase"
                delay={phaseDelay}
                rootMargin="0px 0px -10% 0px"
              >
                <span className="roadmap__node roadmap__node--phase" aria-hidden />
                <h3 className="roadmap__phase-title">{section.label}</h3>
              </Reveal>

              <ol className="roadmap__list">
                {section.items.map((item) => {
                  const itemDelay = step++ * 55

                  return (
                    <Reveal
                      key={item.id}
                      as="li"
                      className="roadmap__item roadmap__reveal roadmap__reveal--item"
                      delay={itemDelay}
                      rootMargin="0px 0px -10% 0px"
                    >
                      <span className="roadmap__node" aria-hidden />
                      <article className="roadmap__card" data-phase={section.id}>
                        <div className="roadmap__card-body">
                          <h4 className="roadmap__card-title">{item.title}</h4>
                          <p className="roadmap__card-text">{item.body}</p>
                          {'points' in item && item.points?.length ? (
                            <ul className="roadmap__points">
                              {item.points.map((point) => (
                                <li key={point}>{point}</li>
                              ))}
                            </ul>
                          ) : null}
                          {'status' in item && item.status ? (
                            <p className="roadmap__status">{item.status}</p>
                          ) : null}
                        </div>
                      </article>
                    </Reveal>
                  )
                })}
              </ol>
            </section>
          )
        })}
      </div>
    </div>
  )
}
