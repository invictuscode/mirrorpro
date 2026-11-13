import type { ReactNode, RefObject } from 'react'

import { MirrorStage, type CameraStyle } from './MirrorStage'
import type { SessionControls } from '../../hooks/useSessionControls'
import { useNow } from '../../hooks/useNow'
import type { TimedSession } from '../../hooks/usePoseStream'
import type { TwoStepConfirm } from '../../hooks/useTwoStepConfirm'
import { formatAngle, angleStatusText } from '../../services/angles'
import { phaseLabel } from '../../services/exercise'
import { buildGuides, buildHighlights, currentCue, type CueKey } from '../../services/guides'
import type { DecodedFrame } from '../../services/streamClient'
import { countdownSeconds, formatDuration, liveTimers } from '../../services/time'
import type { TrackingStatus } from '../../services/trackingStatus'
import type {
  AngleDefinition,
  AngleMeasurement,
  ExerciseDefinition,
  ExerciseState,
  FormRule,
  RuleState,
  RuleStatus,
  Topology,
} from '../../types/protocol'

interface Props {
  session: TimedSession
  definition: ExerciseDefinition | null
  live: ExerciseState | null
  angles: AngleMeasurement[]
  angleDefinitions: AngleDefinition[]
  frameRef: RefObject<DecodedFrame | null>
  topology: Topology | null
  showCamera: boolean
  cameraStyle: CameraStyle
  onToggleCamera: () => void
  showGuides: boolean
  onToggleGuides: () => void
  tracking: TrackingStatus
  controls: SessionControls
  endConfirm: TwoStepConfirm
}

export function SessionScreen(props: Props) {
  const { session, live, controls } = props
  const v = session.view
  // The session's effective rules (e.g. a looser elbow allowance chosen on the
  // settings screen) replace the exercise's defaults everywhere on this screen.
  const definition = props.definition && {
    ...props.definition,
    feedback: { ...props.definition.feedback, form_rules: v.form_rules },
  }
  const now = useNow(250)
  const timers = liveTimers(v, session.receivedAt, now)
  // Live frames are newer than the last session push; use them when they
  // belong to the current set's counter.
  const state = live && live.selection_id === v.selection_id ? live : null
  const reps = state?.reps ?? v.current_set_reps

  // Only label this exercise's angles on the selected/used side(s).
  const joints = new Set(definition?.display_angles ?? [])
  const sides = new Set(state?.sides_used.length ? state.sides_used : v.side ? [v.side] : ['left', 'right'])
  const shownDefs = props.angleDefinitions.filter((d) => joints.has(d.joint) && sides.has(d.side))

  // The practice rep always shows the camera with movement guides.
  const practicing = v.state === 'practice' || (v.state === 'paused' && v.paused_from === 'practice')
  const cameraVisible = props.showCamera || practicing
  const guidesOn = practicing || props.showGuides
  const guides = definition && guidesOn ? buildGuides(definition, props.angleDefinitions, v.rep_counting, state, v.side) : []
  const highlights = definition ? buildHighlights(definition, props.angleDefinitions, state, v.side) : []

  return (
    <section className={`m-session ${cameraVisible ? 'with-camera' : 'counter-only'}`} aria-label={`${v.exercise_name} session`}>
      <header className="m-topbar">
        <div className="m-topbar-title">
          <span className="m-exercise">{v.exercise_name}</span>
          {v.side && <span className="m-muted"> · {v.side === 'left' ? 'Left' : 'Right'}</span>}
        </div>
        <div className="m-topbar-stats">
          {practicing ? <Stat label="Now" value="Practice" /> : <Stat label="Set" value={`${v.current_set} of ${v.plan.sets}`} />}
          <Stat label="Time" value={formatDuration(timers.activeMs)} />
        </div>
      </header>

      <div className="m-main">
        {cameraVisible && (
          <MirrorStage
            frameRef={props.frameRef}
            topology={props.topology}
            angleDefinitions={shownDefs}
            style={props.cameraStyle}
            tracking={props.tracking}
            guides={guides}
            highlights={highlights}
          />
        )}
        <div className="m-side">
          {practicing && definition ? (
            <PracticePanel definition={definition} state={state} minHoldMs={v.rep_counting.min_hold_ms} />
          ) : v.state === 'resting' || (v.state === 'paused' && v.paused_from === 'resting') ? (
            <RestPanel
              remainingMs={timers.restRemainingMs ?? 0}
              nextSet={v.current_set + 1}
              sets={v.plan.sets}
              lastReps={v.sets.at(-1)?.reps ?? 0}
            />
          ) : (
            <>
              <div className="m-reps" aria-live="polite">
                <span className="m-reps-n">{reps}</span>
                <span className="m-reps-of">/ {v.plan.reps_per_set}</span>
              </div>
              <div className="m-phase">{phaseText(state)}</div>
              <div className="m-progress" aria-hidden="true">
                <span style={{ width: `${(state?.progress ?? 0) * 100}%` }} className={state?.phase === 'at_target' ? 'at-target' : ''} />
              </div>
              <div className="m-target-line m-muted">
                Target {v.rep_counting.target_deg > v.rep_counting.start_deg ? '≥' : '≤'} {v.rep_counting.target_deg}°
                {v.rep_counting.min_hold_ms > 0 ? ` · hold ${v.rep_counting.min_hold_ms / 1000} s` : ''}
              </div>
              <DrivingAngle definition={definition} angles={props.angles} sides={[...sides]} />
              <Feedback state={state} />
              {definition && <KeyPoints definition={definition} state={state} />}
              {definition && <Instructions steps={definition.instructions} />}
            </>
          )}
        </div>
      </div>

      <Controls
        session={session}
        controls={controls}
        endConfirm={props.endConfirm}
        showCamera={props.showCamera}
        onToggleCamera={props.onToggleCamera}
        practicing={practicing}
        showGuides={props.showGuides}
        onToggleGuides={props.onToggleGuides}
      />
      {v.state === 'paused' && <PausedOverlay controls={controls} />}
    </section>
  )
}

/** Never give a movement instruction while tracking is unreliable: it would
 * contradict the tracking message shown at the same time. */
function phaseText(state: ExerciseState | null): string {
  if (!state) return 'Get into position'
  if (!state.feedback.tracking_ok) return 'Waiting for clear tracking'
  return phaseLabel(state.phase)
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="m-stat">
      <span className="m-stat-label">{label}</span>
      <span className="m-stat-value">{value}</span>
    </div>
  )
}

function RestPanel({ remainingMs, nextSet, sets, lastReps }: { remainingMs: number; nextSet: number; sets: number; lastReps: number }) {
  return (
    <div className="m-rest" aria-live="polite">
      <div className="m-muted">Set complete · {lastReps} reps</div>
      <div className="m-rest-label">Rest</div>
      <div className="m-rest-count">{formatDuration(countdownSeconds(remainingMs) * 1000)}</div>
      <div className="m-muted">
        Next: set {nextSet} of {sets}
      </div>
    </div>
  )
}

function DrivingAngle({ definition, angles, sides }: { definition: ExerciseDefinition | null; angles: AngleMeasurement[]; sides: string[] }) {
  if (!definition) return null
  const joint = definition.signal.joint
  const label = joint.replaceAll('_', ' ')
  return (
    <div className="m-angles">
      {sides.map((side) => {
        const m = angles.find((a) => a.id === `${side}_${joint}`) ?? null
        return (
          <div key={side} className="m-angle">
            <span className="m-angle-label">
              {sides.length > 1 ? `${side} ` : ''}
              {label}
            </span>
            <span className={`m-angle-value ${formatAngle(m) ? '' : 'invalid'}`}>{formatAngle(m) ?? angleStatusText(m)}</span>
          </div>
        )
      })}
      <div className="m-fine">Estimated by camera</div>
    </div>
  )
}

function Feedback({ state }: { state: ExerciseState | null }) {
  const m = state?.feedback.message
  return (
    <div className="m-feedback-slot" role="status" aria-live="polite" aria-atomic="true">
      {m && (
        <div key={m.seq} className={`m-feedback fb-${m.category}`}>
          {m.text}
        </div>
      )}
    </div>
  )
}

const CUE_ORDER: { key: CueKey; label: string }[] = [
  { key: 'start', label: 'Start' },
  { key: 'move', label: 'Move' },
  { key: 'hold', label: 'Hold' },
  { key: 'back', label: 'Return' },
]

/** One guided repetition before the counted sets: step-by-step cues that
 * follow the person's actual position, matching the arrows on the camera. */
function PracticePanel({ definition, state, minHoldMs }: { definition: ExerciseDefinition; state: ExerciseState | null; minHoldMs: number }) {
  const cue = state?.feedback.tracking_ok === false ? null : currentCue(state, minHoldMs)
  const steps = CUE_ORDER.filter((c) => c.key !== 'hold' || minHoldMs > 0)
  return (
    <div className="m-practice">
      <div className="m-practice-title">Practice repetition</div>
      <p className="m-muted">
        This one does not count. Follow the blue arrow to the green <strong>target</strong> line, then back to the dashed
        start line.
      </p>
      <ol className="m-steps">
        {steps.map((c) => (
          <li key={c.key} className={c.key === cue ? 'current' : ''} aria-current={c.key === cue ? 'step' : undefined}>
            <span className="m-step-label">{c.label}</span>
            <span>{definition.guidance.cues[c.key]}</span>
          </li>
        ))}
      </ol>
      {state?.feedback.tracking_ok === false && <p className="m-muted">Waiting for clear tracking…</p>}
      <Feedback state={state} />
      <KeyPoints definition={definition} state={state} />
      {definition.guidance.tempo && <p className="m-muted">Tempo: {definition.guidance.tempo}</p>}
    </div>
  )
}

const RULE_ICON: Record<RuleState, { icon: string; label: string }> = {
  ok: { icon: '✓', label: 'OK' },
  violated: { icon: '!', label: 'Check this' },
  uncertain: { icon: '?', label: 'Not visible' },
  inactive: { icon: '·', label: 'Checked during the movement' },
}

/** What to keep in mind, with a live status for each joint that must stay
 * steady (the same joints ringed on the camera view). */
function KeyPoints({ definition, state }: { definition: ExerciseDefinition; state: ExerciseState | null }) {
  const live = new Map((state?.feedback.rules ?? []).map((r) => [r.id, r]))
  const rules = definition.feedback.form_rules
  if (rules.length === 0 && definition.guidance.key_points.length === 0) return null
  return (
    <div className="m-keypoints">
      <div className="m-keypoints-title">Keep in mind</div>
      <ul>
        {rules.map((r) => {
          const s = live.get(r.id)
          const st = s?.state ?? 'inactive'
          return (
            <li key={r.id} className={`kp-${st}`}>
              <span className="kp-icon" aria-label={RULE_ICON[st].label}>
                {RULE_ICON[st].icon}
              </span>
              <span>
                {r.message}
                {r.blocks_rep && <span className="kp-required"> Required for the repetition to count.</span>}
                <span className="kp-live">{ruleReading(r, s ?? null)}</span>
              </span>
            </li>
          )
        })}
        {definition.guidance.key_points.map((k) => (
          <li key={k} className="kp-note">
            <span className="kp-icon" aria-hidden="true">
              •
            </span>
            <span>{k}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** What the camera currently measures for a rule, so a patient (or
 * developer) can see why it is or isn't satisfied. */
function ruleReading(rule: FormRule, s: RuleStatus | null): string {
  const limit =
    rule.min_deg !== null && rule.max_deg !== null
      ? `${rule.min_deg}–${rule.max_deg}°`
      : rule.max_deg !== null
        ? `≤ ${rule.max_deg}°`
        : `≥ ${rule.min_deg ?? 0}°`
  if (!s || s.state === 'inactive') return ` Allowed ${limit}.`
  if (s.state === 'uncertain') return ' Not visible to the camera right now.'
  if (s.reason === 'out_of_plane') return ' Bent toward or away from the camera.'
  return ` Now ${Math.round(s.value_deg ?? 0)}° (allowed ${limit}).`
}

function Instructions({ steps }: { steps: string[] }) {
  return (
    <details className="m-instructions">
      <summary>Instructions</summary>
      <ol>
        {steps.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
    </details>
  )
}

function Controls(props: {
  session: TimedSession
  controls: SessionControls
  endConfirm: TwoStepConfirm
  showCamera: boolean
  onToggleCamera: () => void
  practicing: boolean
  showGuides: boolean
  onToggleGuides: () => void
}) {
  const { session, controls, endConfirm } = props
  const v = session.view
  const paused = v.state === 'paused'
  const advanceLabel = props.practicing ? 'Skip practice' : v.state === 'resting' ? 'Skip rest' : 'Finish set'
  return (
    <footer className="m-controls">
      <Btn onClick={() => void (paused ? controls.resume() : controls.pause())} disabled={controls.busy} primary hint="Space">
        {paused ? 'Resume' : 'Pause'}
      </Btn>
      <Btn onClick={() => void controls.advance()} disabled={controls.busy || paused} hint="N">
        {advanceLabel}
      </Btn>
      {!props.practicing && (
        <>
          <Btn onClick={props.onToggleCamera} hint="C" pressed={props.showCamera}>
            {props.showCamera ? 'Hide camera' : 'Camera'}
          </Btn>
          <Btn onClick={props.onToggleGuides} hint="G" pressed={props.showGuides}>
            {props.showGuides ? 'Hide guides' : 'Guides'}
          </Btn>
        </>
      )}
      <Btn onClick={endConfirm.trigger} disabled={controls.busy} danger={endConfirm.pending} hint="E">
        {endConfirm.pending ? 'Press again to end' : 'End session'}
      </Btn>
      {controls.error && (
        <span className="m-error" role="alert">
          {controls.error}
        </span>
      )}
    </footer>
  )
}

function Btn(props: {
  onClick: () => void
  disabled?: boolean
  primary?: boolean
  danger?: boolean
  pressed?: boolean
  hint: string
  children: ReactNode
}) {
  const cls = ['m-btn', props.primary ? 'm-btn-primary' : '', props.danger ? 'm-btn-danger' : ''].join(' ')
  return (
    <button className={cls} onClick={props.onClick} disabled={props.disabled} aria-pressed={props.pressed}>
      {props.children}
      <kbd>{props.hint}</kbd>
    </button>
  )
}

function PausedOverlay({ controls }: { controls: SessionControls }) {
  return (
    <div className="m-paused" role="dialog" aria-label="Session paused">
      <div className="m-paused-title">Paused</div>
      <p className="m-muted">Nothing is counted while paused.</p>
      <button className="m-btn m-btn-primary" onClick={() => void controls.resume()} disabled={controls.busy}>
        Resume <kbd>Space</kbd>
      </button>
    </div>
  )
}
