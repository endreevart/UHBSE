import type { SystemLoad } from '../engine/systems'
import type { SystemId } from '../engine/indicators'
import { useI18n } from '../i18n'
import { systemName } from '../i18n/names'

interface Props {
  loads: SystemLoad[]
  selected: SystemId | null
  onSelect: (s: SystemId) => void
}

/** Systems below this contribute less than a rounding error to the picture. */
const FLOOR = 0.02
const MAX = 6

/**
 * Which systems this protocol is actually moving, widest first.
 *
 * The heatmap can answer this too, but it asks for a scan across seventy rows
 * before it does. A row of chips sized by share answers it in one glance and
 * doubles as the filter for everything below, which is the only reason it earns
 * the space at the top of the workspace.
 */
export function SystemBar({ loads, selected, onSelect }: Props) {
  const { t } = useI18n()
  const shown = loads.filter((l) => l.share >= FLOOR).slice(0, MAX)
  if (shown.length === 0) return null

  const rest = loads.slice(shown.length).reduce((sum, l) => sum + l.share, 0)

  return (
    <div className="sysbar" data-hint={t.ws.hints.systems}>
      <span className="mono-label sysbar__label">{t.ws.systemsMoved}</span>
      <div className="sysbar__track">
        {shown.map((load) => (
          <button
            key={load.system}
            type="button"
            className="sysbar__chip"
            data-on={load.system === selected}
            data-dir={load.signed >= 0 ? 'up' : 'down'}
            onClick={() => onSelect(load.system)}
          >
            <span className="sysbar__name">{systemName(t, load.system)}</span>
            <span className="sysbar__share tabular">{Math.round(load.share * 100)}%</span>
          </button>
        ))}
        {rest > 0.01 && (
          <span className="sysbar__rest">
            <span className="sysbar__name">{t.ws.other}</span>
            <span className="sysbar__share tabular">{Math.round(rest * 100)}%</span>
          </span>
        )}
      </div>
    </div>
  )
}
