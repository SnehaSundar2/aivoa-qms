/** Small presentational primitives shared across the app. */

export function SeverityBadge({ severity, score }) {
  if (!severity) return <span className="badge badge-neutral">Unclassified</span>
  return (
    <span className={`badge badge-${severity.toLowerCase()}`}>
      <span className="badge-dot" />
      {severity}
      {score != null && <span style={{ opacity: 0.7 }}>· {score}</span>}
    </span>
  )
}

const STATUS_TONE = {
  Draft: 'neutral',
  Open: 'brand',
  'Under Investigation': 'major',
  'CAPA Initiated': 'major',
  'Pending Closure': 'brand',
  Closed: 'minor',
  'Rejected / Not a Complaint': 'neutral',
}

export function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${STATUS_TONE[status] ?? 'neutral'}`}>
      {status ?? 'Unknown'}
    </span>
  )
}

export function Alert({ tone = 'info', title, children, onClose, icon }) {
  const defaultIcon = {
    info: 'i',
    warn: '!',
    danger: '!',
    success: '✓',
    ai: '✦',
  }[tone]

  return (
    <div className={`alert alert-${tone}`}>
      <span className="alert-icon">{icon ?? defaultIcon}</span>
      <div style={{ minWidth: 0 }}>
        {title && <strong>{title}</strong>}
        {children}
      </div>
      {onClose && (
        <button className="close" onClick={onClose} aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  )
}

export function Empty({ icon = '□', title, children }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <strong>{title}</strong>
      {children && <span>{children}</span>}
    </div>
  )
}

export function Spinner() {
  return <span className="spinner" />
}

/**
 * Renders the LangGraph node path from the last run.
 *
 * Nodes that fell back to rules are marked, so the operator can see at a
 * glance which parts of the result actually came from the model.
 */
export function TraceStrip({ trace = [] }) {
  if (!trace.length) return null
  return (
    <div className="trace">
      {trace.map((node, index) => {
        const isRules = node.includes('(rules)') || node.includes('failed')
        return (
          <span key={`${node}-${index}`} style={{ display: 'contents' }}>
            {index > 0 && <span className="trace-arrow">›</span>}
            <span className={`trace-node${isRules ? ' is-rules' : ''}`}>
              {node}
            </span>
          </span>
        )
      })}
    </div>
  )
}
