import type { ReactNode } from 'react'

import { VIS_HIGH, VIS_MEDIUM, visibilityColor } from './PoseCanvas'
import type { ConnectionState } from '../services/streamClient'
import { coreVisibility, type TrackingStatus } from '../services/trackingStatus'
import { LM_VISIBILITY, type FrameMessage, type StatusMessage, type Topology } from '../types/protocol'

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

function Row({ label, value, tone }: { label: string; value: ReactNode; tone?: string | undefined }) {
  return (
    <div className="row">
      <span className="row-label">{label}</span>
      <span className={`row-value ${tone ?? ''}`}>{value}</span>
    </div>
  )
}

const fmt = (n: number | undefined, digits = 1) => (n === undefined ? '—' : n.toFixed(digits))

export function StatusPanel({
  connection,
  status,
  tracking,
  message,
}: {
  connection: ConnectionState
  status: StatusMessage | null
  tracking: TrackingStatus
  message: FrameMessage | null
}) {
  const core = message ? coreVisibility(message) : null
  return (
    <Panel title="Status">
      <Row label="Backend" value={connection} tone={connection === 'open' ? 'ok' : 'warn'} />
      <Row label="Camera" value={status?.state ?? '—'} tone={status?.state === 'error' ? 'err' : undefined} />
      <Row label="Tracking" value={tracking.title} tone={`sev-${tracking.severity}`} />
      <Row label="Core visibility" value={core === null ? '—' : fmt(core, 2)} />
      <Row label="Model" value={status?.model ?? '—'} />
      <Row label="Profile" value={status?.profile ?? '—'} />
    </Panel>
  )
}

export function PerformancePanel({
  message,
  receivedFps,
  renderFps,
}: {
  message: FrameMessage | null
  receivedFps: number
  renderFps: number
}) {
  const m = message?.metrics
  return (
    <Panel title="Performance">
      <Row label="Camera FPS" value={fmt(m?.capture_fps)} />
      <Row label="Inference FPS" value={fmt(m?.inference_fps)} />
      <Row label="Inference time" value={m ? `${fmt(m.inference_ms)} ms` : '—'} />
      <Row label="Pipeline latency" value={m ? `${fmt(m.latency_ms, 0)} ms` : '—'} />
      <Row label="Frames received / s" value={fmt(receivedFps)} />
      <Row label="Frames drawn / s" value={fmt(renderFps)} />
      <Row label="Skipped (busy)" value={m?.dropped_frames ?? '—'} />
      <Row label="Source" value={message ? `${message.width}×${message.height}` : '—'} />
    </Panel>
  )
}

/** Major body joints shown in the confidence table (subset of the 33). */
const KEY_LANDMARKS = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]

export function LandmarkPanel({ message, topology }: { message: FrameMessage | null; topology: Topology | null }) {
  const lms = message?.landmarks
  return (
    <Panel title="Landmark visibility">
      <p className="hint">
        Model confidence that each point is visible (0–1). Experimental estimate, not calibrated. ≥{VIS_HIGH} high, ≥
        {VIS_MEDIUM} medium.
      </p>
      <table className="lm-table">
        <tbody>
          {KEY_LANDMARKS.map((i) => {
            const v = lms?.[i]?.[LM_VISIBILITY]
            return (
              <tr key={i}>
                <td>{(topology?.landmark_names[i] ?? `#${i}`).replaceAll('_', ' ')}</td>
                <td className="lm-bar">
                  <span style={{ width: `${(v ?? 0) * 100}%`, background: v === undefined ? 'transparent' : visibilityColor(v) }} />
                </td>
                <td className="lm-value">{v === undefined ? '—' : v.toFixed(2)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Panel>
  )
}
