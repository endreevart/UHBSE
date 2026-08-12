import { useState } from 'react'
import { useI18n } from '../i18n'
import { PartnerContactModal } from './PartnerContactModal'
import { Reveal } from './Reveal'
import { SectionHead } from './SectionHead'

export function SectionPartners() {
  const { t } = useI18n()
  const [contactAudience, setContactAudience] = useState<string | null>(null)

  return (
    <section className="section" id="partners" aria-labelledby="partners-heading">
      <div className="shell">
        <SectionHead
          headingId="partners-heading"
          title={t.partners.title}
        />

        <ol className="partners__list">
          {t.partners.items.map((item, i) => (
            <Reveal as="li" key={item.audience} delay={i * 80}>
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
        </ol>
      </div>

      <PartnerContactModal
        open={contactAudience !== null}
        audience={contactAudience}
        onClose={() => setContactAudience(null)}
      />
    </section>
  )
}
