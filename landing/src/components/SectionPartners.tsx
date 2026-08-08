import { useState } from 'react'
import { useI18n } from '../i18n'
import { PartnerContactModal } from './PartnerContactModal'
import { Reveal } from './Reveal'

export function SectionPartners() {
  const { t } = useI18n()
  const [contactAudience, setContactAudience] = useState<string | null>(null)

  return (
    <section className="section" id="partners">
      <div className="shell">
        <Reveal className="section__head">
          <p className="kicker">{t.partners.kicker}</p>
          <h2 className="display display--l">{t.partners.title}</h2>
        </Reveal>

        <div className="partners__list">
          {t.partners.items.map((item, i) => (
            <Reveal key={item.audience} delay={i * 80}>
              <button
                type="button"
                className="partner-row"
                onClick={() => setContactAudience(item.audience)}
              >
                <span className="partner-row__audience">{item.audience}</span>
                <span className="partner-row__action">{item.action}</span>
                <span className="partner-row__link">
                  {t.partners.cta}
                  <span className="btn__arrow" aria-hidden="true">
                    →
                  </span>
                </span>
              </button>
            </Reveal>
          ))}
        </div>
      </div>

      <PartnerContactModal
        open={contactAudience !== null}
        audience={contactAudience}
        onClose={() => setContactAudience(null)}
      />
    </section>
  )
}
