import type { TrackingStatus } from '../services/trackingStatus'

export function StatusOverlay({ status }: { status: TrackingStatus }) {
  if (status.severity === 'ok') return null
  return (
    <div
      className={`status-overlay ${status.blocking ? 'blocking' : 'banner'} sev-${status.severity}`}
      role={status.severity === 'error' ? 'alert' : 'status'}
      aria-live="polite"
    >
      <div className="status-title">{status.title}</div>
      {status.detail && <div className="status-detail">{status.detail}</div>}
    </div>
  )
}
