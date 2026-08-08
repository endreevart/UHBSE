import { useEffect, useRef, useState } from 'react'
import { LOCALES, useI18n, type LocaleCode } from '../i18n'

function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n()
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const current = LOCALES.find((l) => l.code === locale)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const choose = (code: LocaleCode) => {
    setLocale(code)
    setOpen(false)
  }

  return (
    <div className="lang" ref={boxRef}>
      <button
        type="button"
        className="lang__toggle"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={t.nav.language}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="6.4" stroke="currentColor" strokeWidth="1" />
          <path d="M1.6 8h12.8M8 1.6c1.9 2 2.9 4.1 2.9 6.4S9.9 12.4 8 14.4C6.1 12.4 5.1 10.3 5.1 8S6.1 3.6 8 1.6Z" stroke="currentColor" strokeWidth="1" />
        </svg>
        <span>{current?.short}</span>
        <svg className="lang__chevron" width="9" height="6" viewBox="0 0 10 6" fill="none" aria-hidden="true">
          <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.1" />
        </svg>
      </button>

      {open && (
        <div className="lang__menu" role="listbox" aria-label={t.nav.language}>
          {LOCALES.map((l) => (
            <button
              key={l.code}
              type="button"
              role="option"
              className="lang__item"
              aria-current={l.code === locale}
              aria-selected={l.code === locale}
              onClick={() => choose(l.code)}
            >
              <span>{l.label}</span>
              <span className="lang__code">{l.short}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function Header() {
  const { t } = useI18n()
  const [stuck, setStuck] = useState(false)

  useEffect(() => {
    const onScroll = () => setStuck(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className="header" data-stuck={stuck}>
      <div className="shell header__inner">
        <a className="logo" href="#top">
          UHBSE
        </a>

        <nav className="header__nav">
          <a className="header__link" href="#engine">
            {t.nav.engine}
          </a>
          <a className="header__link" href="#research">
            {t.nav.research}
          </a>
          <a className="header__link" href="#principles">
            {t.nav.principles}
          </a>
          <a className="header__link" href="#partners">
            {t.nav.partners}
          </a>
        </nav>

        <div className="header__right">
          <LanguageSwitcher />
          <a className="btn btn--ghost header__cta" href="#partners">
            {t.nav.cta}
          </a>
        </div>
      </div>
    </header>
  )
}
