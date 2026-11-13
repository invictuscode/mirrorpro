import { basicsErrors, type Basics } from '../../services/authoring'

interface Props {
  basics: Basics
  onChange: (b: Basics) => void
  onNext: () => void
  onCancel: () => void
}

export function BasicsStep({ basics: b, onChange, onNext, onCancel }: Props) {
  const errors = basicsErrors(b)
  const set = <K extends keyof Basics>(k: K, v: Basics[K]) => onChange({ ...b, [k]: v })
  return (
    <section className="t-step">
      <h2>1. Describe the exercise</h2>
      <label className="field">
        <span>Name</span>
        <input value={b.name} maxLength={80} onChange={(e) => set('name', e.target.value)} />
      </label>
      <label className="field">
        <span>Short description</span>
        <input value={b.description} maxLength={400} onChange={(e) => set('description', e.target.value)} />
      </label>
      <label className="field">
        <span>Instructions for the patient (one step per line)</span>
        <textarea rows={4} value={b.instructionsText} onChange={(e) => set('instructionsText', e.target.value)} />
      </label>
      <fieldset className="segmented">
        <legend>Camera view</legend>
        {(['side', 'front'] as const).map((v) => (
          <label key={v}>
            <input type="radio" name="camera-view" checked={b.cameraView === v} onChange={() => set('cameraView', v)} />
            {v === 'side' ? 'Side-on' : 'Facing the camera'}
          </label>
        ))}
      </fieldset>
      <p className="hint">
        Choose the view in which the movement happens across the camera, not toward it — 2D angles cannot see
        movement toward the camera.
      </p>
      <label className="field">
        <span>Camera placement guidance</span>
        <input value={b.cameraGuidance} maxLength={300} onChange={(e) => set('cameraGuidance', e.target.value)} />
      </label>
      <p className="hint">
        Patient-facing text must not claim that a movement is safe, or diagnose or prescribe; such wording is rejected.
      </p>
      <div className="button-row">
        <button className="btn btn-primary" disabled={errors.length > 0} onClick={onNext}>
          Next: demonstration
        </button>
        <button className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {errors.length > 0 && <p className="hint">{errors.join(' ')}</p>}
    </section>
  )
}
