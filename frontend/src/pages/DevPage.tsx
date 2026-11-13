import { useCallback, useEffect, useRef, useState } from 'react'

import { AnglesPanel } from '../components/AnglesPanel'
import { ExercisePanel } from '../components/ExercisePanel'
import { FeedbackBanner } from '../components/FeedbackBanner'
import { FeedbackPanel } from '../components/FeedbackPanel'
import { LandmarkPanel, Panel, PerformancePanel, StatusPanel } from '../components/Panels'
import { PoseCanvas } from '../components/PoseCanvas'
import { RepOverlay } from '../components/RepOverlay'
import { StatusOverlay } from '../components/StatusOverlay'
import { useExercises } from '../hooks/useExercises'
import { RateCounter, usePoseStream } from '../hooks/usePoseStream'
import { ApiError, getAngleDefinitions, getTopology, startCamera, stopCamera } from '../services/api'
import { describeTrackingStatus } from '../services/trackingStatus'
import type { AngleDefinition, Topology } from '../types/protocol'

/** Developer console: camera view plus diagnostics. The future mirror layout
 * will reuse the same stream and canvas without the diagnostic panels. */
export function DevPage() {
  const stream = usePoseStream()
  const { connection, status, snapshot, applyStatus } = stream
  const [topology, setTopology] = useState<Topology | null>(null)
  const [angleDefinitions, setAngleDefinitions] = useState<AngleDefinition[]>([])
  const [showAngles, setShowAngles] = useState(true)
  const [mirrored, setMirrored] = useState(true)
  const [showVideo, setShowVideo] = useState(true)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const drawn = useRef(new RateCounter())
  const [renderFps, setRenderFps] = useState(0)
  const stageRef = useRef<HTMLDivElement>(null)
  const liveExercise = snapshot.message?.exercise ?? null
  const exercises = useExercises(
    connection === 'open',
    snapshot.message ? (liveExercise?.selection_id ?? null) : undefined,
  )

  // Topology and angle definitions are static; fetch once the backend is reachable.
  useEffect(() => {
    if (connection !== 'open' || topology) return
    Promise.all([getTopology(), getAngleDefinitions()])
      .then(([topo, defs]) => {
        setTopology(topo)
        setAngleDefinitions(defs)
      })
      .catch((err: unknown) => setActionError(err instanceof Error ? err.message : String(err)))
  }, [connection, topology])

  useEffect(() => {
    const t = window.setInterval(() => setRenderFps(drawn.current.rate()), 250)
    return () => window.clearInterval(t)
  }, [])

  const onDraw = useCallback(() => drawn.current.tick(), [])

  const running = status?.state === 'running'
  const transitioning = status?.state === 'starting' || status?.state === 'stopping'

  const toggleCamera = async () => {
    setBusy(true)
    setActionError(null)
    try {
      applyStatus(await (running ? stopCamera() : startCamera()))
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const toggleFullscreen = () => {
    const req = document.fullscreenElement ? document.exitFullscreen() : stageRef.current?.requestFullscreen()
    req?.catch((err: unknown) => setActionError(`Fullscreen unavailable: ${String(err)}`))
  }

  const tracking = describeTrackingStatus(connection, status, snapshot.message, snapshot.frameAgeMs)

  return (
    <div className="dev-layout">
      <header className="app-header">
        <div className="brand">
          <span className="brand-name">PT Smart Mirror</span>
          <span className="brand-sub">
            Developer console · tracking, angles, exercises, feedback · <a href="#/">Mirror view</a> · <a href="#/therapist">Therapist workspace</a>
          </span>
        </div>
        <div className="controls">
          <button
            className={`btn ${running ? 'btn-secondary' : 'btn-primary'}`}
            onClick={() => void toggleCamera()}
            disabled={busy || transitioning || connection !== 'open'}
          >
            {busy || transitioning ? 'Working…' : running ? 'Stop camera' : 'Start camera'}
          </button>
          <label className="toggle">
            <input type="checkbox" checked={mirrored} onChange={(e) => setMirrored(e.target.checked)} />
            Mirror view
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={showVideo}
              onChange={(e) => setShowVideo(e.target.checked)}
              disabled={status?.preview_enabled === false}
            />
            Show video
          </label>
          <label className="toggle">
            <input type="checkbox" checked={showAngles} onChange={(e) => setShowAngles(e.target.checked)} />
            Angle labels
          </label>
          <button className="btn btn-ghost" onClick={toggleFullscreen}>
            Fullscreen
          </button>
        </div>
      </header>

      {(actionError ?? stream.protocolError) && (
        <div className="action-error" role="alert">
          {actionError ?? `Stream error: ${stream.protocolError}`}
        </div>
      )}

      <main className="dev-main">
        <div className="stage" ref={stageRef}>
          <PoseCanvas
            frameRef={stream.frameRef}
            topology={topology}
            mirrored={mirrored}
            showVideo={showVideo}
            angleDefinitions={angleDefinitions}
            showAngles={showAngles}
            onDraw={onDraw}
          />
          {/* Bottom bar: counter and feedback side by side, never overlapping. */}
          <div className="stage-hud">
            <RepOverlay active={exercises.active} live={liveExercise} />
            <FeedbackBanner active={exercises.active} live={liveExercise} />
          </div>
          <StatusOverlay status={tracking} />
        </div>

        <aside className="sidebar">
          <ExercisePanel exercises={exercises} live={liveExercise} />
          <FeedbackPanel active={exercises.active} live={liveExercise} />
          <AnglesPanel definitions={angleDefinitions} message={snapshot.message} />
          <StatusPanel connection={connection} status={status} tracking={tracking} message={snapshot.message} />
          <PerformancePanel message={snapshot.message} receivedFps={snapshot.receivedFps} renderFps={renderFps} />
          <LandmarkPanel message={snapshot.message} topology={topology} />
          <Panel title="Privacy">
            <p className="hint">
              Video is processed on this computer only. Frames are not saved or uploaded; the preview is sent only to
              this local page.
            </p>
          </Panel>
        </aside>
      </main>

      <footer className="notice">
        Research prototype — not clinically validated and not a substitute for a licensed physical therapist. Landmark
        positions are experimental computer-vision estimates.
      </footer>
    </div>
  )
}
