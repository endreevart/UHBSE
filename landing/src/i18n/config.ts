export const LOCALES = [
  { code: 'en', label: 'English', short: 'EN', dir: 'ltr' },
  { code: 'ru', label: 'Русский', short: 'RU', dir: 'ltr' },
  { code: 'ar', label: 'العربية', short: 'AR', dir: 'ltr' },
  { code: 'zh', label: '中文', short: 'ZH', dir: 'ltr' },
  { code: 'es', label: 'Español', short: 'ES', dir: 'ltr' },
  { code: 'fr', label: 'Français', short: 'FR', dir: 'ltr' },
  { code: 'de', label: 'Deutsch', short: 'DE', dir: 'ltr' },
] as const

export type LocaleCode = (typeof LOCALES)[number]['code']
