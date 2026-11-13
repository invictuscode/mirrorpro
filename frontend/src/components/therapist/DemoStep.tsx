import { useEffect, useRef, useState } from 'react'

import { PoseCanvas } from '../PoseCanvas'
import { StatusOverlay } from '../StatusOverlay'
import type { PoseStream } from '../../hooks/usePoseStream'
import { startCamera } from '../../services/api'
import {
  cancelLiveRecording,
  liveStatus,
  startLiveRecording,
  stopLiveRecording,
  uploadDemonstration,
} from '../../services/authoringApi'
import { describeTrackingStatus } from '../../services/trackingStatus'
import { formatDuration } from '../../services/time'
import type { DemonstrationInfo, LiveRecordingStatus } from '../../types/authoring'
import type { Topology } from '../../types/protocol'

interface Props {
  stream: PoseStream
  topology: Topology | null
  onRecorded: (demo: DemonstrationInfo) => void
  onBack: () => void
}

const COUNTDOWN_S = 3

/** Record a demonstration with the camera, or upload a video. Either way only
 * joint angles are extracted; no video is stored. */
export function DemoStep({ stream, topology, onRecorded, onBack }: Props) {
  const [mode, setMode] = useState<'record' | 'upload'>('record')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [countdown, setCountdown] = useState<number | null>(null)
  const [rec, setRec] = useState<LiveRecordingStatus | null>(null)
  const timers = useRef<number[]>([])
  const running = stream.status?.state === 'running'

  useEffect(() => {
    const ts = timers.current
    return () => {
      ts.forEach((t) => window.clearTimeout(t))
      // Leaving the step mid-recording must not leave the recorder running.
      void cancelLiveRecording().catch((err: unknown) => console.warn('Could not cancel recording', err))
    }
  }, [])

  // Poll the elapsed time while recording.
  useEffect(() => {
    if (!rec?.recording) return
    const t = window.setInterval(() => {
      liveStatus()
        .then(setRec)
        .catch((err: unknown) => setError(String(err)))
    }, 400)
    return () => window.clearInterval(t)
  }, [rec?.recording])

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const ensureCamera = () =>
    run(async () => {
      const s = await startCamera()
      stream.applyStatus(s)
      if (s.state !== 'running') throw new Error(s.error?.message ?? 'Camera could not be started')
    })

  const beginCountdown = () => {
    setError(null)
    setCountdown(COUNTDOWN_S)
    for (let i = 1; i <= COUNTDOWN_S; i++) {
      timers.current.push(
        window.setTimeout(() => {
          const left = COUNTDOWN_S - i
          setCountdown(left > 0 ? left : null)
          if (left === 0) void run(async () => setRec(await startLiveRecording()))
        }, i * 1000),
      )
    }
  }

  const stop = () =>
    run(async () => {
      const demo = await stopLiveRecording()
      setRec(null)
      onRecorded(demo)
    })

  const onFile = (file: File | undefined) => {
    if (!file) return
    void run(async () => onRecorded(await uploadDemonstration(file)))
  }

  const tracking = describeTrackingStatus(stream.connection, stream.status, stream.snapshot.message, stream.snapshot.frameAgeMs)

  return (
    <section className="t-step">
      <h2>2. Demonstrate the movement</h2>
      <fieldset className="segmented">
        <legend>Source</legend>
        <label>
          <input type="radio" name="demo-mode" checked={mode === 'record'} onChange={() => setMode('record')} disabled={busy || !!rec?.recording} />
          Record with the camera
        </label>
        <label>
          <input type="radio" name="demo-mode" checked={mode === 'upload'} onChange={() => setMode('upload')} disabled={busy || !!rec?.recording} />
          Upload a video
        </label>
      </fieldset>

      {mode === 'record' ? (
        <>
          <ul className="hint t-tips">
            <li>Start and finish in the start position.</li>
            <li>Perform 3–5 steady repetitions the way the patient should.</li>
            <li>Keep the whole body in view, in the camera view you chose.</li>
          </ul>
          <div className="t-live">
            <PoseCanvas frameRef={stream.frameRef} topology={topology} mirrored showVideo angleDefinitions={[]} showAngles={false} />
            <StatusOverlay status={tracking} />
            {countdown !== null && <div className="t-countdown">{countdown}</div>}
            {rec?.recording && (
              <div className="t-rec-badge" role="status">
                ● Recording {formatDuration(rec.elapsed_ms)} / {formatDuration(rec.max_ms)}
              </div>
            )}
          </div>
          <div className="button-row">
            {!running ? (
              <button className="btn btn-primary" onClick={() => void ensureCamera()} disabled={busy}>
                Start camera
              </button>
            ) : rec?.recording ? (
              <button className="btn btn-primary" onClick={() => void stop()} disabled={busy}>
                Stop recording
              </button>
            ) : (
              <button className="btn btn-primary" onClick={beginCountdown} disabled={busy || countdown !== null}>
                Record demonstration
              </button>
            )}
            <button className="btn btn-ghost" onClick={onBack} disabled={busy || !!rec?.recording}>
              Back
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="hint">
            The video is processed on this computer to extract joint angles, then deleted immediately. It is never
            stored or uploaded anywhere else. MP4 (H.264) works best; up to 2 minutes.
          </p>
          <input type="file" accept="video/*" disabled={busy} onChange={(e) => onFile(e.target.files?.[0])} />
          {busy && <p className="hint">Processing video on this computer…</p>}
          <div className="button-row">
            <button className="btn btn-ghost" onClick={onBack} disabled={busy}>
              Back
            </button>
          </div>
        </>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
