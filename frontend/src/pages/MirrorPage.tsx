import { useCallback, useEffect, useRef, useState } from 'react'

import { HomeScreen } from '../components/mirror/HomeScreen'
import { CAMERA_STYLE_LABEL, type CameraStyle } from '../components/mirror/MirrorStage'
import { SessionScreen } from '../components/mirror/SessionScreen'
import { SettingsScreen } from '../components/mirror/SettingsScreen'
import { SummaryScreen } from '../components/mirror/SummaryScreen'
import { useExerciseDefinition } from '../hooks/useExerciseDefinition'
import { usePoseStream } from '../hooks/usePoseStream'
import { useSessionControls } from '../hooks/useSessionControls'
import { useTwoStepConfirm } from '../hooks/useTwoStepConfirm'
import { getAngleDefinitions, getTopology, listExercises } from '../services/api'
import { describeTrackingStatus } from '../services/trackingStatus'
import { PROTOCOL_VERSION, type AngleDefinition, type ExerciseSummary, type Topology } from '../types/protocol'
import '../mirror.css'

const STYLES: CameraStyle[] = ['video', 'skeleton']
const STYLE_KEY = 'ptm.mirror.cameraStyle'
const CAMERA_KEY = 'ptm.mirror.showCamera'
const GUIDES_KEY = 'ptm.mirror.showGuides'

/** Per-device display preferences; storage may be unavailable (private mode),
 * in which case the defaults are used. */
function loadPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = window.localStorage.getItem(key)
    return allowed.includes(v as T) ? (v as T) : fallback
  } catch {
    return fallback
  }
}

function savePref(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch (err) {
    console.warn('Could not remember display preference', err)
  }
}

/**
 * Patient-facing screen for a display behind a two-way mirror (or a TV/laptop).
 * Large type, one thing at a time; diagnostics live in the developer console.
 *
 * Keyboard: Space pause/resume · N finish set / skip rest · E end (press twice)
 * · C show/hide camera · G show/hide movement guides · D video or points only
 * · F fullscreen. (N also skips the practice repetition.)
 */
export function MirrorPage() {
  const stream = usePoseStream()
  const controls = useSessionControls(stream)
  const { connection, status, snapshot, session } = stream
  const [library, setLibrary] = useState<ExerciseSummary[]>([])
  const [topology, setTopology] = useState<Topology | null>(null)
  const [angleDefs, setAngleDefs] = useState<AngleDefinition[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  // Counter-only by default; the Camera button splits the screen.
  const [showCamera, setShowCamera] = useState(() => loadPref(CAMERA_KEY, ['on', 'off'], 'off') === 'on')
  const [cameraStyle, setCameraStyle] = useState<CameraStyle>(() => loadPref(STYLE_KEY, STYLES, 'video'))
  // Guides are always on during the practice rep; afterwards this preference applies.
  const [showGuides, setShowGuides] = useState(() => loadPref(GUIDES_KEY, ['on', 'off'], 'off') === 'on')
  const [setupFor, setSetupFor] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const { definition } = useExerciseDefinition(session?.view.exercise_id ?? null)
  const endSession = controls.end
  const endConfirm = useTwoStepConfirm(useCallback(() => void endSession(), [endSession]))

  useEffect(() => {
    if (connection !== 'open') return
    Promise.all([listExercises(), getTopology(), getAngleDefinitions()])
      .then(([lib, topo, defs]) => {
        setLibrary(lib)
        setTopology(topo)
        setAngleDefs(defs)
        setLoadError(null)
      })
      .catch((err: unknown) => setLoadError(err instanceof Error ? err.message : String(err)))
  }, [connection])

  // Once a session exists, the settings screen has done its job.
  useEffect(() => {
    if (session) setSetupFor(null)
  }, [session])

  const toggleCamera = useCallback(() => {
    setShowCamera((on) => {
      savePref(CAMERA_KEY, on ? 'off' : 'on')
      return !on
    })
  }, [])

  const toggleGuides = useCallback(() => {
    setShowGuides((on) => {
      savePref(GUIDES_KEY, on ? 'off' : 'on')
      return !on
    })
  }, [])

  const cycleStyle = useCallback(() => {
    setCameraStyle((st) => {
      const next = STYLES[(STYLES.indexOf(st) + 1) % STYLES.length] ?? 'video'
      savePref(STYLE_KEY, next)
      return next
    })
  }, [])

  const toggleFullscreen = useCallback(() => {
    const req = document.fullscreenElement ? document.exitFullscreen() : rootRef.current?.requestFullscreen()
    req?.catch((err: unknown) => console.warn('Fullscreen unavailable', err))
  }, [])

  // Keyboard shortcuts (a mirror rarely has a mouse). E needs two presses.
  const v = session?.view
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const key = e.key.toLowerCase()
      if (key === 'f') toggleFullscreen()
      else if (key === 'd') cycleStyle()
      else if (key === 'c') toggleCamera()
      else if (key === 'g') toggleGuides()
      if (!v || !['practice', 'active', 'resting', 'paused'].includes(v.state) || controls.busy) return
      if (key === ' ') {
        e.preventDefault()
        void (v.state === 'paused' ? controls.resume() : controls.pause())
      } else if (key === 'n' && v.state !== 'paused') {
        void controls.advance()
      } else if (key === 'e') {
        endConfirm.trigger()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [v, controls, toggleFullscreen, cycleStyle, toggleCamera, toggleGuides, endConfirm])

  const tracking = describeTrackingStatus(connection, status, snapshot.message, snapshot.frameAgeMs)
  const inProgress = v && ['practice', 'active', 'resting', 'paused'].includes(v.state)

  let content
  if (status && status.protocol_version !== PROTOCOL_VERSION) {
    content = (
      <div className="m-center">
        <div className="m-title">Update needed</div>
        <p className="m-muted">{tracking.detail}</p>
      </div>
    )
  } else if (connection !== 'open') {
    content = (
      <div className="m-center">
        <div className="m-title">{connection === 'connecting' ? 'Connecting…' : 'Waiting for the tracking service'}</div>
        {connection === 'closed' && <p className="m-muted">Start the backend; this screen reconnects automatically.</p>}
      </div>
    )
  } else if (!session && setupFor) {
    content = (
      <SettingsScreen
        exerciseId={setupFor}
        busy={controls.busy}
        error={controls.error}
        onBegin={(req) => void controls.start(req)}
        onBack={() => {
          controls.clearError()
          setSetupFor(null)
        }}
      />
    )
  } else if (!session) {
    content = <HomeScreen library={library} onChoose={setSetupFor} />
  } else if (inProgress) {
    content = (
      <SessionScreen
        session={session}
        definition={definition}
        live={snapshot.message?.exercise ?? null}
        angles={snapshot.message?.angles ?? []}
        angleDefinitions={angleDefs}
        frameRef={stream.frameRef}
        topology={topology}
        showCamera={showCamera}
        cameraStyle={cameraStyle}
        onToggleCamera={toggleCamera}
        showGuides={showGuides}
        onToggleGuides={toggleGuides}
        tracking={tracking}
        controls={controls}
        endConfirm={endConfirm}
      />
    )
  } else {
    content = <SummaryScreen view={session.view} definition={definition} controls={controls} />
  }

  return (
    <div className="mirror" ref={rootRef}>
      <nav className="m-util" aria-label="Display options">
        <button onClick={cycleStyle} title="Camera view style (D)">
          Camera: {CAMERA_STYLE_LABEL[cameraStyle]}
        </button>
        <button onClick={toggleFullscreen} title="Fullscreen (F)">
          Fullscreen
        </button>
        <a href="#/dev">Developer console</a>
      </nav>
      {(loadError ?? (!session && !setupFor ? controls.error : null)) && (
        <div className="m-alert" role="alert">
          {loadError ?? controls.error}
        </div>
      )}
      <main className="m-content">{content}</main>
      <footer className="m-disclaimer">
        Research prototype · not clinically validated · not a substitute for your physical therapist · camera images
        stay on this device
      </footer>
    </div>
  )
}
