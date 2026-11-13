import { useState } from 'react'

import { DemoChart } from './DemoChart'
import { JOINT_LABEL, newSteadyRule, parseInstructions } from '../../services/authoring'
import type { AnalysisResult, CustomExercise, DraftFields } from '../../types/authoring'
import type { FormRule, RepCountingConfig } from '../../types/protocol'

interface Props {
  fields: DraftFields
  onChange: (f: DraftFields) => void
  analysis: AnalysisResult | null
  record: CustomExercise | null
  hasDemo: boolean
  busy: boolean
  error: string | null
  onSave: (storeAngleData: boolean) => void
  onApprove: (reviewer: string, attestation: boolean) => void
  onArchive: () => void
  onClose: () => void
}

export function ParametersEditor(p: Props) {
  const f = p.fields
  const rc = f.rep_counting
  const [consent, setConsent] = useState(false)
  const [instructionsText, setInstructionsText] = useState(f.instructions.join('\n'))
  const [reviewer, setReviewer] = useState('')
  const [attest, setAttest] = useState(false)
  const [steadyJoint, setSteadyJoint] = useState('')
  const set = <K extends keyof DraftFields>(k: K, v: DraftFields[K]) => p.onChange({ ...f, [k]: v })
  const setRc = <K extends keyof RepCountingConfig>(k: K, v: RepCountingConfig[K]) => set('rep_counting', { ...rc, [k]: v })
  const setRule = (i: number, r: FormRule | null) =>
    set('form_rules', r ? f.form_rules.map((x, j) => (j === i ? r : x)) : f.form_rules.filter((_, j) => j !== i))
  const status = p.record?.status
  const approvedLive = p.record?.live_version
  // Approval applies to the saved version, so it must match what is on screen.
  const unsaved = p.record !== null && JSON.stringify(f) !== JSON.stringify(p.record.fields)

  return (
    <section className="t-step">
      <h2>{p.record ? `${f.name} — version ${p.record.version}` : '4. Edit the parameters'}</h2>
      {p.record && (
        <p className={`t-status t-status-${status}`}>
          {status === 'draft' && 'Draft — not visible to patients.'}
          {status === 'approved' && `Approved by ${p.record.approved_by}; offered to patients.`}
          {status === 'archived' && 'Archived — not offered to patients.'}
          {status === 'draft' && approvedLive ? ` Patients currently get approved version ${approvedLive}.` : ''}
        </p>
      )}
      {status === 'approved' && <p className="hint">Saving changes creates a new version that must be approved again.</p>}

      {p.analysis?.chart && (
        <DemoChart
          title={`${JOINT_LABEL[f.signal_joint] ?? f.signal_joint} during the demonstration, with your current thresholds`}
          tMs={p.analysis.chart.t_ms}
          deg={p.analysis.chart.deg}
          reps={p.analysis.reps}
          startDeg={rc.start_deg}
          targetDeg={rc.target_deg}
        />
      )}

      <div className="t-form-grid">
        <label className="field">
          <span>Name</span>
          <input value={f.name} onChange={(e) => set('name', e.target.value)} />
        </label>
        <label className="field">
          <span>Description</span>
          <input value={f.description} onChange={(e) => set('description', e.target.value)} />
        </label>
        <label className="field t-wide">
          <span>Instructions (one step per line)</span>
          <textarea
            rows={3}
            value={instructionsText}
            onChange={(e) => {
              setInstructionsText(e.target.value)
              set('instructions', parseInstructions(e.target.value))
            }}
          />
        </label>
        <label className="field t-wide">
          <span>Camera placement guidance</span>
          <input value={f.camera_guidance} onChange={(e) => set('camera_guidance', e.target.value)} />
        </label>

        <label className="field">
          <span>Joint that drives the count</span>
          <select value={f.signal_joint} onChange={(e) => set('signal_joint', e.target.value)}>
            {Object.entries(JOINT_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Sides</span>
          <select
            value={f.side_mode === 'single' ? (f.default_side ?? 'right') : 'both'}
            onChange={(e) =>
              p.onChange(
                e.target.value === 'both'
                  ? { ...f, side_mode: 'mean_of_visible', default_side: null }
                  : { ...f, side_mode: 'single', default_side: e.target.value as 'left' | 'right' },
              )
            }
          >
            <option value="left">One side (default left)</option>
            <option value="right">One side (default right)</option>
            <option value="both">Both sides (whichever is visible)</option>
          </select>
        </label>
        <label className="field">
          <span>Camera view</span>
          <select value={f.camera_view} onChange={(e) => set('camera_view', e.target.value as 'front' | 'side')}>
            <option value="side">Side-on</option>
            <option value="front">Facing the camera</option>
          </select>
        </label>

        <Num label="Start angle (°)" value={rc.start_deg} onChange={(v) => setRc('start_deg', v)} />
        <Num label="Target angle (°)" value={rc.target_deg} onChange={(v) => setRc('target_deg', v)} />
        <Num label="Hysteresis (°)" value={rc.hysteresis_deg} onChange={(v) => setRc('hysteresis_deg', v)} hint="Margin to leave a zone; prevents double counts" />
        <Num label="Hold at target (s)" value={rc.min_hold_ms / 1000} step={0.25} onChange={(v) => setRc('min_hold_ms', Math.round(v * 1000))} />
        <Num label="Minimum repetition time (s)" value={rc.min_rep_ms / 1000} step={0.1} onChange={(v) => setRc('min_rep_ms', Math.round(v * 1000))} />
        <Num label="Maximum repetition time (s)" value={rc.max_rep_ms / 1000} step={1} onChange={(v) => setRc('max_rep_ms', Math.round(v * 1000))} />
        <Num label="Default sets" value={f.dosage.sets ?? 1} onChange={(v) => set('dosage', { ...f.dosage, sets: v })} />
        <Num label="Default repetitions per set" value={f.dosage.reps_per_set ?? 10} onChange={(v) => set('dosage', { ...f.dosage, reps_per_set: v })} />
        <label className="field t-wide">
          <span>Message when the target is not reached (optional)</span>
          <input
            value={f.target_not_reached_message ?? ''}
            maxLength={120}
            placeholder="Try to move a little further toward the target."
            onChange={(e) => set('target_not_reached_message', e.target.value.trim() ? e.target.value : null)}
          />
        </label>
      </div>

      <h3 className="subhead">Joints that must stay steady, and other form rules</h3>
      <p className="hint">
        A rule that blocks repetitions makes the exercise impossible to complete with the wrong joint: a repetition
        during which the rule is broken, or its joint is out of view for much of the time, is not counted.
      </p>
      {f.form_rules.length === 0 && <p className="hint">None.</p>}
      {f.form_rules.map((r, i) => (
        <div key={r.id} className="t-rule">
          <input value={r.message} maxLength={120} onChange={(e) => setRule(i, { ...r, message: e.target.value })} aria-label="Message to the patient" />
          <span className="hint">{JOINT_LABEL[r.joint] ?? r.joint} between</span>
          <input
            type="number"
            className="t-rule-num"
            aria-label="Minimum angle (empty for none)"
            placeholder="0"
            value={r.min_deg ?? ''}
            onChange={(e) => setRule(i, { ...r, min_deg: e.target.value === '' ? null : Number(e.target.value) })}
          />
          <span className="hint">and</span>
          <input
            type="number"
            className="t-rule-num"
            aria-label="Maximum angle (empty for none)"
            placeholder="180"
            value={r.max_deg ?? ''}
            onChange={(e) => setRule(i, { ...r, max_deg: e.target.value === '' ? null : Number(e.target.value) })}
          />
          <span className="hint">°</span>
          <label className="t-radio-row">
            <input type="checkbox" checked={r.blocks_rep} onChange={(e) => setRule(i, { ...r, blocks_rep: e.target.checked })} />
            Blocks the repetition
          </label>
          <button className="btn btn-ghost" onClick={() => setRule(i, null)}>
            Remove
          </button>
        </div>
      ))}

      <div className="t-add-steady">
        <label className="field">
          <span>Add a joint that must stay steady</span>
          <select value={steadyJoint} onChange={(e) => setSteadyJoint(e.target.value)}>
            <option value="">Choose a joint…</option>
            {Object.entries(JOINT_LABEL)
              .filter(([k]) => k !== f.signal_joint)
              .map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
          </select>
        </label>
        <button
          className="btn btn-secondary"
          disabled={!steadyJoint}
          onClick={() => {
            set('form_rules', [...f.form_rules, newSteadyRule(steadyJoint, f.form_rules)])
            setSteadyJoint('')
          }}
        >
          Add
        </button>
        <span className="hint">
          Starts as “held straight, ≤ 30°, blocks repetitions”; edit the limits above after adding.
        </span>
      </div>

      {!p.record && p.hasDemo && (
        <label className="t-radio-row t-consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          Save the demonstration's joint-angle data with this exercise (for later review). No video is ever saved. Leave
          unticked to keep only the parameters.
        </label>
      )}

      {p.error && (
        <p className="form-error" role="alert">
          {p.error}
        </p>
      )}
      <div className="button-row">
        {status !== 'archived' && (
          <button className="btn btn-primary" onClick={() => p.onSave(consent)} disabled={p.busy}>
            {p.record ? 'Save changes' : 'Save as draft'}
          </button>
        )}
        {p.record && status !== 'archived' && (
          <button className="btn btn-ghost" onClick={p.onArchive} disabled={p.busy}>
            Archive
          </button>
        )}
        <button className="btn btn-ghost" onClick={p.onClose} disabled={p.busy}>
          Close
        </button>
      </div>

      {status === 'draft' && (
        <div className="t-approve">
          <h3 className="subhead">Approve for patients</h3>
          <label className="field">
            <span>Reviewing therapist</span>
            <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Full name" />
          </label>
          <label className="t-radio-row">
            <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
            I have reviewed these parameters, instructions and reminders, and consider them appropriate for the patients
            this exercise will be offered to. I understand the angles are camera estimates.
          </label>
          <button
            className="btn btn-primary"
            disabled={p.busy || unsaved || reviewer.trim().length < 2 || !attest}
            onClick={() => p.onApprove(reviewer.trim(), attest)}
          >
            Approve version {p.record?.version}
          </button>
          {unsaved && <p className="form-error">You have unsaved changes. Save them before approving.</p>}
        </div>
      )}
    </section>
  )
}

function Num(props: { label: string; value: number; onChange: (v: number) => void; step?: number; hint?: string }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <input
        type="number"
        step={props.step ?? 1}
        value={Number.isFinite(props.value) ? props.value : ''}
        onChange={(e) => props.onChange(e.target.value === '' ? Number.NaN : Number(e.target.value))}
      />
      {props.hint && <span className="hint">{props.hint}</span>}
    </label>
  )
}
