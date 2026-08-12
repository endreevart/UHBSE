import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { en, type Dict } from './locales/en'
import { ru } from './locales/ru'
import { ar } from './locales/ar'
import { zh } from './locales/zh'
import { es } from './locales/es'
import { fr } from './locales/fr'
import { de } from './locales/de'
import { applySeoMeta } from '../lib/seo'

export { LOCALES, type LocaleCode } from './config'
import type { LocaleCode } from './config'

const DICTS: Record<LocaleCode, Dict> = { en, ru, ar, zh, es, fr, de }

const STORAGE_KEY = 'uhbse.locale'

function detectLocale(): LocaleCode {
  if (typeof window === 'undefined') return 'en'
  // an explicit ?lang= wins so shared links always open in the intended language
  const url = new URLSearchParams(window.location.search).get('lang') as LocaleCode | null
  if (url && url in DICTS) return url
  const stored = window.localStorage.getItem(STORAGE_KEY) as LocaleCode | null
  if (stored && stored in DICTS) return stored
  for (const nav of navigator.languages ?? [navigator.language]) {
    const base = nav.slice(0, 2).toLowerCase() as LocaleCode
    if (base in DICTS) return base
  }
  return 'en'
}

interface I18nValue {
  locale: LocaleCode
  /** Document layout direction — always LTR so chrome stays in place. */
  dir: 'ltr'
  /** Reading direction for localized copy (Arabic reads RTL inside LTR layout). */
  textDir: 'ltr' | 'rtl'
  t: Dict
  setLocale: (code: LocaleCode) => void
  fmt: (template: string, values: Record<string, string | number>) => string
  num: (value: number, digits?: number) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<LocaleCode>(() => detectLocale())

  const textDir = locale === 'ar' ? 'rtl' : 'ltr'
  const t = DICTS[locale]

  useEffect(() => {
    const root = document.documentElement
    root.lang = locale
    root.dir = 'ltr'
    root.dataset.locale = locale
    root.dataset.textDir = textDir
    applySeoMeta(locale, t.meta)
  }, [locale, textDir, t])

  const setLocale = useCallback((code: LocaleCode) => {
    setLocaleState(code)
    try {
      window.localStorage.setItem(STORAGE_KEY, code)
    } catch {
      /* storage unavailable — selection stays for this session only */
    }
  }, [])

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      dir: 'ltr' as const,
      textDir,
      t,
      setLocale,
      fmt: (template, values) =>
        template.replace(/\{(\w+)\}/g, (_, key: string) => String(values[key] ?? `{${key}}`)),
      num: (v, digits = 0) =>
        new Intl.NumberFormat(locale === 'ar' ? 'ar-u-nu-latn' : locale, {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        }).format(v),
    }),
    [locale, textDir, t, setLocale],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used inside I18nProvider')
  return ctx
}
