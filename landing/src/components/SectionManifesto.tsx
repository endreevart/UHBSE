import { useI18n } from '../i18n'
import { Reveal } from './Reveal'
import { SectionHead } from './SectionHead'

export function SectionManifesto() {
  const { t } = useI18n()
  const m = t.manifesto

  const lines: { text: string; variant: 'lead' | 'body' | 'final' }[] = [
    { text: m.l1, variant: 'lead' },
    { text: m.l2, variant: 'body' },
    { text: m.l3, variant: 'body' },
    { text: m.l4, variant: 'body' },
    { text: m.l5, variant: 'body' },
    { text: m.l6, variant: 'final' },
  ]

  return (
    <section className="section section--flush manifesto" id="manifesto" aria-labelledby="manifesto-heading">
      <div className="spectral-wash" style={{ insetBlockStart: 0 }} aria-hidden="true" />
      <div className="shell">
        <SectionHead
          headingId="manifesto-heading"
          title={m.title}
          titleClass="display display--m"
        />
        <div className="manifesto__lines">
          {lines.map((line, i) => (
            <Reveal key={line.text} delay={i * 90}>
              <p className={`manifesto__line manifesto__line--${line.variant}`}>{line.text}</p>
            </Reveal>
          ))}
        </div>
      </div>
      <div className="spectral-wash" style={{ insetBlockEnd: 0, insetBlockStart: 'auto' }} aria-hidden="true" />
    </section>
  )
}
