import type { ConnectionState } from './streamClient'
import { LM_VISIBILITY, PROTOCOL_VERSION, type FrameMessage, type StatusMessage } from '../types/protocol'

export type Severity = 'ok' | 'info' | 'warning' | 'error'

export interface TrackingStatus {
  severity: Severity
  title: string
  detail?: string
  /** Covers the camera view (vs. a banner over a live view). */
  blocking: boolean
}

/** Shoulders and hips: if these are unreliable, the whole-body pose is too. */
export const CORE_LANDMARKS = [11, 12, 23, 24] as const
export const UNCERTAIN_CORE_VISIBILITY = 0.5
export const STALE_FRAME_MS = 2000

export function coreVisibility(message: FrameMessage): number | null {
  const lms = message.landmarks
  if (!lms) return null
  const values = CORE_LANDMARKS.map((i) => lms[i]?.[LM_VISIBILITY] ?? 0)
  return values.reduce((a, b) => a + b, 0) / values.length
}

/** Single, prioritised description of what the user should know right now. */
export function describeTrackingStatus(
  connection: ConnectionState,
  status: StatusMessage | null,
  message: FrameMessage | null,
  frameAgeMs: number | null,
): TrackingStatus {
  if (connection !== 'open' || !status) {
    return connection === 'connecting'
      ? { severity: 'info', title: 'Connecting to tracking service…', blocking: true }
      : {
          severity: 'error',
          title: 'Tracking service not reachable',
          detail: 'Start the backend (see README) — this page reconnects automatically.',
          blocking: true,
        }
  }
  if (status.protocol_version !== PROTOCOL_VERSION) {
    return {
      severity: 'error',
      title: 'Frontend and backend versions differ',
      detail: `Backend speaks protocol v${status.protocol_version}, this page expects v${PROTOCOL_VERSION}. Restart both.`,
      blocking: true,
    }
  }
  switch (status.state) {
    case 'error':
      return {
        severity: 'error',
        title: errorTitle(status),
        detail: status.error?.message ?? 'Unknown error',
        blocking: true,
      }
    case 'stopped':
      return { severity: 'info', title: 'Camera is off', detail: 'Press Start camera to begin tracking.', blocking: true }
    case 'starting':
      return { severity: 'info', title: 'Starting camera…', blocking: true }
    case 'stopping':
      return { severity: 'info', title: 'Stopping camera…', blocking: true }
    case 'running':
      break
  }
  if (!message || frameAgeMs === null) {
    return { severity: 'info', title: 'Waiting for first frame…', blocking: true }
  }
  if (frameAgeMs > STALE_FRAME_MS) {
    return {
      severity: 'warning',
      title: 'No new frames',
      detail: `Last frame ${(frameAgeMs / 1000).toFixed(1)} s ago.`,
      blocking: false,
    }
  }
  if (!message.person_detected) {
    return {
      severity: 'warning',
      title: 'No person detected',
      detail: 'Step into view so your whole body is visible.',
      blocking: false,
    }
  }
  const core = coreVisibility(message)
  if (core !== null && core < UNCERTAIN_CORE_VISIBILITY) {
    return {
      severity: 'warning',
      title: 'Tracking uncertain',
      detail: 'Shoulders and hips are not clearly visible. Improve lighting or step back.',
      blocking: false,
    }
  }
  return { severity: 'ok', title: 'Person detected', blocking: false }
}

function errorTitle(status: StatusMessage): string {
  switch (status.error?.code) {
    case 'camera_open_failed':
      return 'Camera unavailable'
    case 'camera_read_failed':
      return 'Camera stopped responding'
    case 'model_missing':
      return 'Pose model not installed'
    case 'detector_init_failed':
      return 'Pose model failed to load'
    case 'inference_failed':
      return 'Pose tracking failed'
    default:
      return 'Tracking error'
  }
}
