import type { SessionView } from '../types/protocol'

/** "m:ss" (or "h:mm:ss" past an hour). Negative values clamp to 0. */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

/** Seconds countdown rounded up, so "0" only shows when time is really up. */
export function countdownSeconds(ms: number): number {
  return Math.max(0, Math.ceil(ms / 1000))
}

/**
 * Extrapolate a session's timers from when it was received. The backend only
 * pushes on state changes; between pushes active time grows while active and
 * rest counts down while resting.
 */
export function liveTimers(view: SessionView, receivedAt: number, now: number) {
  const dt = Math.max(0, now - receivedAt)
  return {
    activeMs: view.active_ms + (view.state === 'active' ? dt : 0),
    restRemainingMs:
      view.rest_remaining_ms === null ? null : Math.max(0, view.rest_remaining_ms - (view.state === 'resting' ? dt : 0)),
  }
}
