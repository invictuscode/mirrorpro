import { useCallback, useState } from 'react'

import type { PoseStream } from './usePoseStream'
import {
  advanceSession,
  dismissSession,
  endSession,
  pauseSession,
  resumeSession,
  startCamera,
  startSession,
} from '../services/api'
import type { SessionView, StartSessionRequest } from '../types/protocol'

export interface SessionControls {
  busy: boolean
  error: string | null
  clearError: () => void
  start: (req: StartSessionRequest) => Promise<void>
  pause: () => Promise<void>
  resume: () => Promise<void>
  advance: () => Promise<void>
  end: () => Promise<void>
  dismiss: () => Promise<void>
}

/** Session commands. Results are applied immediately; the WebSocket push that
 * follows carries the same state. */
export function useSessionControls(stream: PoseStream): SessionControls {
  const { status, applyStatus, applySession } = stream
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(
    async (action: () => Promise<SessionView | null>) => {
      setBusy(true)
      setError(null)
      try {
        applySession(await action())
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setBusy(false)
      }
    },
    [applySession],
  )

  const start = useCallback(
    (req: StartSessionRequest) =>
      run(async () => {
        // The session needs the camera; start it first and stop on failure so
        // the patient never faces a counter that cannot count.
        if (status?.state !== 'running') {
          const cam = await startCamera()
          applyStatus(cam)
          if (cam.state !== 'running') throw new Error(cam.error?.message ?? 'The camera could not be started.')
        }
        return startSession(req)
      }),
    [run, status?.state, applyStatus],
  )

  return {
    busy,
    error,
    clearError: () => setError(null),
    start,
    pause: () => run(pauseSession),
    resume: () => run(resumeSession),
    advance: () => run(advanceSession),
    end: () => run(endSession),
    dismiss: () => run(async () => (await dismissSession(), null)),
  }
}
