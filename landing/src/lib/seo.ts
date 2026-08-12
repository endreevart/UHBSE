import { LOCALES, type LocaleCode } from '../i18n/config'
import type { Dict } from '../i18n/locales/en'
import { OG_IMAGE_URL, SITE_NAME, SITE_URL } from './site'

const LOCALE_TO_OG: Record<LocaleCode, string> = {
  en: 'en_US',
  ru: 'ru_RU',
  ar: 'ar_AR',
  zh: 'zh_CN',
  es: 'es_ES',
  fr: 'fr_FR',
  de: 'de_DE',
}

const JSON_LD_ID = 'uhbse-jsonld'

function pageUrl(locale: LocaleCode): string {
  return locale === 'en' ? `${SITE_URL}/` : `${SITE_URL}/?lang=${locale}`
}

function upsertMeta(attr: 'name' | 'property', key: string, content: string): void {
  let el = document.querySelector(`meta[${attr}="${key}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

function upsertLink(rel: string, href: string, hreflang?: string): void {
  const selector = hreflang
    ? `link[rel="${rel}"][hreflang="${hreflang}"]`
    : `link[rel="${rel}"]:not([hreflang])`
  let el = document.querySelector(selector) as HTMLLinkElement | null
  if (!el) {
    el = document.createElement('link')
    el.rel = rel
    if (hreflang) el.hreflang = hreflang
    document.head.appendChild(el)
  }
  el.href = href
}

function upsertJsonLd(locale: LocaleCode, meta: Dict['meta'], url: string): void {
  let el = document.getElementById(JSON_LD_ID) as HTMLScriptElement | null
  if (!el) {
    el = document.createElement('script')
    el.id = JSON_LD_ID
    el.type = 'application/ld+json'
    document.head.appendChild(el)
  }

  const payload = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'WebPage',
        '@id': `${url}#webpage`,
        url,
        name: meta.title,
        description: meta.description,
        inLanguage: locale,
        isPartOf: { '@id': `${SITE_URL}/#website` },
        about: { '@id': `${SITE_URL}/#organization` },
      },
      {
        '@type': 'WebSite',
        '@id': `${SITE_URL}/#website`,
        url: SITE_URL,
        name: SITE_NAME,
        alternateName: [
          'Universal Human Biology Simulation Engine',
          'Human Biology Simulation Engine',
          'Human simulator',
        ],
        description: meta.description,
        inLanguage: locale,
      },
      {
        '@type': 'Organization',
        '@id': `${SITE_URL}/#organization`,
        name: SITE_NAME,
        alternateName: [
          'Universal Human Biology Simulation Engine',
          'Human Biology Simulation Engine',
        ],
        url: SITE_URL,
        logo: OG_IMAGE_URL,
        description: meta.description,
      },
    ],
  }

  el.textContent = JSON.stringify(payload)
}

export function applySeoMeta(locale: LocaleCode, meta: Dict['meta']): void {
  const url = pageUrl(locale)

  document.title = meta.title

  upsertMeta('name', 'description', meta.description)
  upsertMeta('name', 'robots', 'index, follow, max-image-preview:large')
  upsertMeta('name', 'googlebot', 'index, follow')

  upsertLink('canonical', url)

  upsertMeta('property', 'og:type', 'website')
  upsertMeta('property', 'og:site_name', SITE_NAME)
  upsertMeta('property', 'og:title', meta.title)
  upsertMeta('property', 'og:description', meta.description)
  upsertMeta('property', 'og:url', url)
  upsertMeta('property', 'og:locale', LOCALE_TO_OG[locale])
  upsertMeta('property', 'og:image', OG_IMAGE_URL)

  upsertMeta('name', 'twitter:card', 'summary')
  upsertMeta('name', 'twitter:title', meta.title)
  upsertMeta('name', 'twitter:description', meta.description)
  upsertMeta('name', 'twitter:image', OG_IMAGE_URL)

  document.querySelectorAll('link[rel="alternate"][hreflang]').forEach((node) => node.remove())

  for (const loc of LOCALES) {
    upsertLink('alternate', pageUrl(loc.code), loc.code)
  }
  upsertLink('alternate', `${SITE_URL}/`, 'x-default')

  upsertJsonLd(locale, meta, url)
}
