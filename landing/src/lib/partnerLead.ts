const DEFAULT_ENDPOINT = 'https://formsubmit.co/ajax/info@tykmyk.ru'

export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
}

export async function submitPartnerLead(payload: {
  email: string
  audience: string
  locale: string
}): Promise<boolean> {
  const endpoint = import.meta.env.VITE_PARTNER_LEAD_URL ?? DEFAULT_ENDPOINT
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      email: payload.email.trim(),
      audience: payload.audience,
      locale: payload.locale,
      _subject: `UHBSE — ${payload.audience}`,
      _template: 'table',
      _captcha: 'false',
    }),
  })
  return res.ok
}
