import { useEffect, useState } from 'react'

import { useExerciseDefinition } from '../../hooks/useExerciseDefinition'
import {
  LIMITS,
  defaultsFor,
  describeThresholds,
  ruleErrors,
  ruleOverrides,
  toStartRequest,
  validateSettings,
  type SettingsDraft,
} from '../../services/sessionSettings'
import type { ExerciseDefinition, FormRule, StartSessionRequest } from '../../types/protocol'

interface Props {
  exerciseId: string
  busy: boolean
  error: string | null
  onBegin: (req: StartSessionRequest) => void
  onBack: () => void
}

/** Shown after pressing Start: keep the defaults or adjust them, then begin. */
export function SettingsScreen({ exerciseId, busy, error, onBegin, onBack }: Props) {
  const { definition: def, error: loadError } = useExerciseDefinition(exerciseId)
  const [draft, setDraft] = useState<SettingsDraft | null>(null)
  const [practice, setPractice] = useState(true)
  const [rules, setRules] = useState<FormRule[]>([])
  useEffect(() => {
    setDraft(def ? defaultsFor(def) : null)
    setRules(def ? def.feedback.form_rules : [])
  }, [def])

  if (loadError) return <p className="m-error">{loadError}</p>
  if (!def || !draft) return <p className="m-muted">Loading…</p>

  const defaults = defaultsFor(def)
  const overrides = ruleOverrides(def.feedback.form_rules, rules)
  const errors = [...validateSettings(def, draft), ...ruleErrors(rules)]
  const changed = JSON.stringify(draft) !== JSON.stringify(defaults) || Object.keys(overrides).length > 0
  const words = describeThresholds(def, draft)
  const set = <K extends keyof SettingsDraft>(key: K, value: SettingsDraft[K]) => setDraft({ ...draft, [key]: value })

  return (
    <section className="m-settings" aria-labelledby="m-settings-title">
      <h1 id="m-settings-title" className="m-title">
        {def.name}
      </h1>
      <HowTo def={def} />
      <p className="m-muted">Keep the default settings, or adjust them to what your therapist asked for.</p>

      {draft.side !== null && (
        <div className="m-field">
          <span className="m-field-label">Side</span>
          <div className="m-segmented" role="radiogroup" aria-label="Side">
            {(['left', 'right'] as const).map((s) => (
              <button key={s} role="radio" aria-checked={draft.side === s} className={draft.side === s ? 'on' : ''} onClick={() => set('side', s)}>
                {s === 'left' ? 'Left' : 'Right'}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="m-settings-grid">
        <Stepper label="Starting angle" unit="°" value={draft.startDeg} limits={LIMITS.angle} onChange={(v) => set('startDeg', v)} hint={words.start} />
        <Stepper label="Target angle" unit="°" value={draft.targetDeg} limits={LIMITS.angle} onChange={(v) => set('targetDeg', v)} hint={words.target} />
        <Stepper
          label="Hold at target"
          unit="s"
          value={draft.holdS}
          limits={LIMITS.holdS}
          onChange={(v) => set('holdS', v)}
          hint={draft.holdS > 0 ? 'Stay at the target this long for the repetition to count' : 'No hold needed'}
        />
        <Stepper label="Sets" value={draft.sets} limits={LIMITS.sets} onChange={(v) => set('sets', v)} />
        <Stepper label="Repetitions per set" value={draft.repsPerSet} limits={LIMITS.repsPerSet} onChange={(v) => set('repsPerSet', v)} />
        <Stepper label="Rest between sets" unit="s" value={draft.restS} limits={LIMITS.restS} onChange={(v) => set('restS', v)} />
      </div>

      {def.clinical_review.status === 'unreviewed_demo' && (
        <p className="m-demo-note">
          The defaults are demonstration values for testing the software, not clinical targets. Use the values your
          physical therapist gave you.
        </p>
      )}
      {rules.length > 0 && <FormChecks rules={rules} onChange={setRules} />}

      {errors.length > 0 && (
        <ul className="m-error m-settings-errors" role="alert">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {error && (
        <p className="m-error" role="alert">
          {error}
        </p>
      )}

      <label className="m-check">
        <input type="checkbox" checked={practice} onChange={(e) => setPractice(e.target.checked)} />
        Start with a practice repetition (shows arrows on the camera; does not count)
      </label>

      <div className="m-summary-actions">
        <button
          className="m-btn m-btn-primary"
          disabled={busy}
          onClick={() => onBegin({ ...toStartRequest(def, { ...defaults, side: draft.side }), practice })}
        >
          Begin with defaults
        </button>
        <button className="m-btn" disabled={busy || !changed || errors.length > 0} onClick={() => onBegin({ ...toStartRequest(def, draft), practice, rule_overrides: overrides })}>
          Begin with these settings
        </button>
        <button
          className="m-btn"
          disabled={busy || !changed}
          onClick={() => {
            setDraft({ ...defaults, side: draft.side })
            setRules(def.feedback.form_rules)
          }}
        >
          Reset
        </button>
        <button className="m-btn m-btn-quiet" disabled={busy} onClick={onBack}>
          Back
        </button>
      </div>
    </section>
  )
}

/** Allowances for joints that should stay steady: how much movement is fine
 * before it counts against the rep, and whether it blocks the rep at all. */
function FormChecks({ rules, onChange }: { rules: FormRule[]; onChange: (r: FormRule[]) => void }) {
  const set = (i: number, patch: Partial<FormRule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <div className="m-formchecks">
      <h2 className="m-howto-title">Form checks</h2>
      <p className="m-muted">
        Some movement is normal. A repetition only fails a check that is <strong>required</strong> if the joint stays
        outside its allowance for a real part of the repetition, not for a brief wobble.
      </p>
      {rules.map((r, i) => (
        <div key={r.id} className="m-formcheck">
          <div className="m-formcheck-text">{r.message}</div>
          <div className="m-formcheck-controls">
            {r.max_deg !== null && (
              <Stepper
                label={`${r.joint.replaceAll('_', ' ')}: allowed up to`}
                unit="°"
                value={r.max_deg}
                limits={{ min: 0, max: 180, step: 5 }}
                onChange={(v) => set(i, { max_deg: v })}
              />
            )}
            {r.min_deg !== null && (
              <Stepper
                label={`${r.joint.replaceAll('_', ' ')}: allowed down to`}
                unit="°"
                value={r.min_deg}
                limits={{ min: 0, max: 180, step: 5 }}
                onChange={(v) => set(i, { min_deg: v })}
              />
            )}
            <label className="m-check">
              <input type="checkbox" checked={r.blocks_rep} onChange={(e) => set(i, { blocks_rep: e.target.checked })} />
              Required for the repetition to count (otherwise a reminder only)
            </label>
          </div>
        </div>
      ))}
    </div>
  )
}

interface StepperProps {
  label: string
  value: number
  unit?: string
  hint?: string
  limits: { min: number; max: number; step: number }
  onChange: (v: number) => void
}

/** Large −/+ control (works with touch, mouse or keyboard) plus direct entry. */
function Stepper({ label, value, unit, hint, limits, onChange }: StepperProps) {
  const clamp = (v: number) => Math.min(limits.max, Math.max(limits.min, Math.round(v / limits.step) * limits.step))
  const id = `st-${label.replace(/\W+/g, '-').toLowerCase()}`
  return (
    <div className="m-field">
      <label className="m-field-label" htmlFor={id}>
        {label}
      </label>
      <div className="m-stepper">
        <button aria-label={`Decrease ${label}`} onClick={() => onChange(clamp(value - limits.step))} disabled={value <= limits.min}>
          −
        </button>
        <input
          id={id}
          type="number"
          inputMode="decimal"
          value={Number.isFinite(value) ? value : ''}
          min={limits.min}
          max={limits.max}
          step={limits.step}
          onChange={(e) => onChange(e.target.value === '' ? Number.NaN : Number(e.target.value))}
        />
        {unit && <span className="m-stepper-unit">{unit}</span>}
        <button aria-label={`Increase ${label}`} onClick={() => onChange(clamp(value + limits.step))} disabled={value >= limits.max}>
          +
        </button>
      </div>
      {hint && <span className="m-field-hint">{hint}</span>}
    </div>
  )
}

/** Setup, what must stay steady, and key points — before the patient starts. */
function HowTo({ def }: { def: ExerciseDefinition }) {
  const g = def.guidance
  const required = def.feedback.form_rules.filter((r) => r.blocks_rep)
  if (g.setup.length === 0 && g.key_points.length === 0 && required.length === 0) return null
  return (
    <div className="m-howto">
      {g.setup.length > 0 && (
        <div>
          <h2 className="m-howto-title">Set up</h2>
          <ol>
            {g.setup.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ol>
        </div>
      )}
      <div>
        <h2 className="m-howto-title">How to do it</h2>
        <ol>
          <li>{g.cues.start}</li>
          <li>{g.cues.move}</li>
          {def.rep_counting.min_hold_ms > 0 && <li>{g.cues.hold}</li>}
          <li>{g.cues.back}</li>
        </ol>
        {g.tempo && <p className="m-muted">Tempo: {g.tempo}</p>}
      </div>
      {(required.length > 0 || g.key_points.length > 0) && (
        <div>
          <h2 className="m-howto-title">Keep in mind</h2>
          <ul>
            {required.map((r) => (
              <li key={r.id}>
                <strong>{r.message}</strong> Repetitions that break this are not counted.
              </li>
            ))}
            {g.key_points.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
