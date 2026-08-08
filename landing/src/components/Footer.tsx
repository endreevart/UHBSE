import { useI18n } from '../i18n'

export function Footer() {
  const { t } = useI18n()
  const year = new Date().getFullYear()

  return (
    <footer className="footer">
      <div className="shell footer__inner">
        <div>
          <div className="logo" style={{ fontSize: 13, marginBlockEnd: 8 }}>
            UHBSE
          </div>
          <p className="footer__tag">{t.footer.tagline}</p>
        </div>
        <p className="footer__note">{t.footer.research}</p>
        <p className="footer__note tabular">
          © {year} UHBSE. {t.footer.rights}
        </p>
      </div>
    </footer>
  )
}
