import { useI18n } from '../i18n'

export function Footer() {
  const { t } = useI18n()
  const year = new Date().getFullYear()

  return (
    <footer className="footer">
      <div className="shell footer__inner">
        <div>
          <p className="logo" style={{ fontSize: 13, marginBlockEnd: 8 }}>
            UHBSE
          </p>
          <p className="footer__tag">{t.footer.tagline}</p>
        </div>
        <p className="footer__note">{t.footer.research}</p>
        <p className="footer__note tabular">
          <small>
            © {year} UHBSE. {t.footer.rights}
          </small>
        </p>
      </div>
    </footer>
  )
}
