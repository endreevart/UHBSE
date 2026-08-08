import { useEffect, useId, useRef, useState } from 'react'
import { useI18n } from '../i18n'
import { isValidEmail, submitPartnerLead } from '../lib/partnerLead'

interface Props {
  open: boolean
  audience: string | null
  onClose: () => void
}

export function PartnerContactModal({ open, audience, onClose }: Props) {
  const { t, locale, fmt } = useI18n()
  const titleId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (!open) return
    setEmail('')
    setStatus('idle')
    setTouched(false)
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0)
    document.body.style.overflow = 'hidden'
    return () => {
      window.clearTimeout(timer)
      document.body.style.overflow = ''
    }
  }, [open, audience])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || !audience) return null

  const invalid = touched && !isValidEmail(email)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setTouched(true)
    if (!isValidEmail(email)) return

    setStatus('submitting')
    if (!audience) return
    try {
      const ok = await submitPartnerLead({ email, audience, locale })
      setStatus(ok ? 'success' : 'error')
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="partner-modal" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <button type="button" className="partner-modal__backdrop" onClick={onClose} aria-label={t.partners.modal.close} />
      <div className="partner-modal__card">
        <header className="partner-modal__head">
          <div>
            <p className="kicker">{t.partners.kicker}</p>
            <h3 className="partner-modal__title" id={titleId}>
              {t.partners.modal.title}
            </h3>
          </div>
          <button type="button" className="partner-modal__close" onClick={onClose} aria-label={t.partners.modal.close}>
            ×
          </button>
        </header>

        {status === 'success' ? (
          <div className="partner-modal__success">
            <p className="partner-modal__success-title">{t.partners.modal.successTitle}</p>
            <p className="partner-modal__success-body">{t.partners.modal.successBody}</p>
            <button type="button" className="btn btn--primary partner-modal__done" onClick={onClose}>
              {t.partners.modal.close}
            </button>
          </div>
        ) : (
          <>
            <p className="partner-modal__lead">{fmt(t.partners.modal.lead, { audience })}</p>
            <form className="partner-modal__form" onSubmit={onSubmit} noValidate>
              <label className="partner-modal__field">
                <span className="mono-label">{t.partners.modal.emailLabel}</span>
                <input
                  ref={inputRef}
                  type="email"
                  name="email"
                  autoComplete="email"
                  inputMode="email"
                  placeholder={t.partners.modal.emailPlaceholder}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onBlur={() => setTouched(true)}
                  disabled={status === 'submitting'}
                  aria-invalid={invalid || undefined}
                />
              </label>
              {invalid && <p className="partner-modal__error">{t.partners.modal.invalidEmail}</p>}
              {status === 'error' && <p className="partner-modal__error">{t.partners.modal.error}</p>}
              <p className="partner-modal__note">{t.partners.modal.privacy}</p>
              <div className="partner-modal__actions">
                <button type="button" className="btn btn--ghost" onClick={onClose} disabled={status === 'submitting'}>
                  {t.partners.modal.cancel}
                </button>
                <button type="submit" className="btn btn--primary" disabled={status === 'submitting'}>
                  {status === 'submitting' ? t.partners.modal.sending : t.partners.modal.submit}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
