import type { Baselines, Subject } from '../engine/subject'
import { useI18n } from '../i18n'
import { SubjectCard } from './SubjectCard'

interface Props {
  open: boolean
  subject: Subject
  baselines: Baselines
  onClose: () => void
  onChange: (next: Subject) => void
}

export function SubjectDrawer({ open, subject, baselines, onClose, onChange }: Props) {
  const { t } = useI18n()
  if (!open) return null

  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={t.engine.subjectTitle}>
      <button type="button" className="drawer__backdrop" onClick={onClose} aria-label={t.ws.drawerClose} />
      <aside className="drawer__panel">
        <header className="drawer__head">
          <h3 className="pane__title">{t.engine.subjectTitle}</h3>
          <button type="button" className="drawer__close" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="drawer__body">
          <SubjectCard subject={subject} baselines={baselines} onChange={onChange} />
        </div>
      </aside>
    </div>
  )
}
