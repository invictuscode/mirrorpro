import { useEffect, useState } from 'react'

import { Panel } from './Panels'
import type { Exercises } from '../hooks/useExercises'
import { getExercise } from '../services/api'
import { describeRepEvent, phaseLabel } from '../services/exercise'
import type { ExerciseDefinition, ExerciseState, RepCountingOverrides, Side } from '../types/protocol'

/** Choose an exercise, adjust its thresholds, and watch repetition counting. */
export function ExercisePanel({ exercises, live }: { exercises: Exercises; live: ExerciseState | null }) {
  const { active } = exercises
  return (
    <Panel title="Exercise">
      {active ? <ActiveView exercises={exercises} live={live} /> : <SetupForm exercises={exercises} />}
      {exercises.error && (
        <p className="form-error" role="alert">
          {exercises.error}
        </p>
      )}
    </Panel>
  )
}

function SetupForm({ exercises }: { exercises: Exercises }) {
  const [selectedId, setSelectedId] = useState('')
  const [definition, setDefinition] = useState<ExerciseDefinition | null>(null)
  const [side, setSide] = useState<Side>('right')
  const [startDeg, setStartDeg] = useState('')
  const [targetDeg, setTargetDeg] = useState('')
  const [holdMs, setHoldMs] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (!selectedId) {
      setDefinition(null)
      return
    }
    let cancelled = false
    getExercise(selectedId)
      .then((d) => {
        if (cancelled) return
        setDefinition(d)
        setSide(d.signal.default_side ?? 'right')
        setStartDeg(String(d.rep_counting.start_deg))
        setTargetDeg(String(d.rep_counting.target_deg))
        setHoldMs(String(d.rep_counting.min_hold_ms))
        setLoadError(null)
      })
      .catch((err: unknown) => !cancelled && setLoadError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const start = () => {
    if (!definition) return
    // Send only values the user changed from the preset.
    const overrides: RepCountingOverrides = {}
    const base = definition.rep_counting
    if (Number(startDeg) !== base.start_deg) overrides.start_deg = Number(startDeg)
    if (Number(targetDeg) !== base.target_deg) overrides.target_deg = Number(targetDeg)
    if (Number(holdMs) !== base.min_hold_ms) overrides.min_hold_ms = Number(holdMs)
    const chosenSide = definition.signal.side_mode === 'single' ? side : null
    void exercises.select(definition.id, chosenSide, overrides)
  }

  const numbersValid = [startDeg, targetDeg, holdMs].every((v) => v.trim() !== '' && Number.isFinite(Number(v)))

  return (
    <div className="form">
      <label className="field">
        <span>Exercise</span>
        <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
          <option value="">Choose…</option>
          {exercises.library.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
              {x.is_demo ? ' (demo)' : ''}
            </option>
          ))}
        </select>
      </label>

      {loadError && <p className="form-error">{loadError}</p>}

      {definition && (
        <>
          <p className="hint">{definition.description}</p>
          <p className="hint">
            <strong>Camera: {definition.camera.view} view.</strong> {definition.camera.guidance}
          </p>
          {definition.signal.side_mode === 'single' && (
            <fieldset className="segmented">
              <legend>Side</legend>
              {(['left', 'right'] as const).map((s) => (
                <label key={s}>
                  <input type="radio" name="side" checked={side === s} onChange={() => setSide(s)} />
                  {s === 'left' ? 'Left' : 'Right'}
                </label>
              ))}
            </fieldset>
          )}
          <div className="field-row">
            <NumberField label="Start (°)" value={startDeg} onChange={setStartDeg} />
            <NumberField label="Target (°)" value={targetDeg} onChange={setTargetDeg} />
            <NumberField label="Hold (ms)" value={holdMs} onChange={setHoldMs} step={100} />
          </div>
          {definition.clinical_review.status === 'unreviewed_demo' && <DemoNotice />}
          <button
            className="btn btn-primary"
            onClick={start}
            disabled={exercises.busy || !numbersValid}
          >
            Start exercise
          </button>
        </>
      )}
    </div>
  )
}

function NumberField(props: { label: string; value: string; onChange: (v: string) => void; step?: number }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <input
        type="number"
        inputMode="decimal"
        value={props.value}
        step={props.step ?? 1}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </label>
  )
}

function DemoNotice() {
  return (
    <p className="demo-notice">
      Demonstration values for software testing — not reviewed by a clinician. Targets should be set by the treating
      therapist.
    </p>
  )
}

function ActiveView({ exercises, live }: { exercises: Exercises; live: ExerciseState | null }) {
  const active = exercises.active
  if (!active) return null
  const { exercise: def, effective_rep_counting: rc } = active
  const state = live?.selection_id === active.selection_id ? live : null
  const event = state?.last_event ? describeRepEvent(state.last_event) : null
  const perSet = def.dosage.reps_per_set

  return (
    <div className="active-exercise">
      <div className="active-head">
        <div>
          <div className="active-name">{def.name}</div>
          <div className="hint">
            {active.side ? `${active.side === 'left' ? 'Left' : 'Right'} side · ` : ''}
            {def.camera.view} view · start {rc.start_deg}° → target {rc.target_deg}°
            {rc.min_hold_ms ? ` · hold ${rc.min_hold_ms} ms` : ''}
          </div>
        </div>
        <div className="rep-count" aria-live="polite">
          <span className="rep-number">{state?.reps ?? 0}</span>
          <span className="rep-label">{perSet ? `of ${perSet} reps` : 'reps'}</span>
        </div>
      </div>

      <div className="phase-line">
        <span>{state ? phaseLabel(state.phase) : 'Waiting for tracking…'}</span>
        <span className="hint">{state?.signal_deg != null ? `${Math.round(state.signal_deg)}°` : 'not tracked'}</span>
      </div>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((state?.progress ?? 0) * 100)}>
        <span style={{ width: `${(state?.progress ?? 0) * 100}%` }} className={state?.phase === 'at_target' ? 'at-target' : ''} />
      </div>
      {state?.phase === 'at_target' && rc.min_hold_ms > 0 && (
        <div className="hint">
          Holding {(state.hold_ms / 1000).toFixed(1)} / {(rc.min_hold_ms / 1000).toFixed(1)} s
        </div>
      )}
      {event && <p className={`rep-event ${event.counted ? 'counted' : 'not-counted'}`}>{event.text}</p>}

      <ol className="instructions">
        {def.instructions.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="hint">
        <strong>Camera:</strong> {def.camera.guidance}
      </p>
      {def.safety_notes.length > 0 && (
        <ul className="safety">
          {def.safety_notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {def.clinical_review.status === 'unreviewed_demo' && <DemoNotice />}

      <div className="button-row">
        <button className="btn btn-secondary" onClick={() => void exercises.reset()} disabled={exercises.busy}>
          Reset count
        </button>
        <button className="btn btn-ghost" onClick={() => void exercises.clear()} disabled={exercises.busy}>
          End exercise
        </button>
      </div>
    </div>
  )
}
