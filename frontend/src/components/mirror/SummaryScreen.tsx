import type { SessionControls } from '../../hooks/useSessionControls'
import { describeUncounted } from '../../services/exercise'
import { formatDuration } from '../../services/time'
import type { ExerciseDefinition, SessionView } from '../../types/protocol'

interface Props {
  view: SessionView
  definition: ExerciseDefinition | null
  controls: SessionControls
}

export function SummaryScreen({ view, definition, controls }: Props) {
  const s = view.summary
  if (!s) return null
  const uncounted = describeUncounted(s.uncounted)
  const joint = definition?.signal.joint.replaceAll('_', ' ')
  // Repeat with exactly the same settings, including any custom thresholds.
  const rc = view.rep_counting
  const repeat = () =>
    void controls.dismiss().then(() =>
      controls.start({
        exercise_id: view.exercise_id,
        side: view.side,
        sets: view.plan.sets,
        reps_per_set: view.plan.reps_per_set,
        rest_s: view.plan.rest_s,
        overrides: { start_deg: rc.start_deg, target_deg: rc.target_deg, min_hold_ms: rc.min_hold_ms },
        rule_overrides: Object.fromEntries(
          view.form_rules.map((r) => [r.id, { min_deg: r.min_deg, max_deg: r.max_deg, blocks_rep: r.blocks_rep }]),
        ),
      }),
    )

  return (
    <section className="m-summary" aria-labelledby="m-summary-title">
      <h1 id="m-summary-title" className="m-title">
        {view.state === 'completed' ? 'Session complete' : 'Session ended'}
      </h1>
      <p className="m-muted">
        {view.exercise_name}
        {view.side ? ` · ${view.side === 'left' ? 'Left' : 'Right'}` : ''}
      </p>

      <div className="m-summary-hero">
        <div>
          <div className="m-summary-big">{s.total_reps}</div>
          <div className="m-muted">repetitions counted</div>
        </div>
        <div>
          <div className="m-summary-big">
            {s.sets_completed}/{view.plan.sets}
          </div>
          <div className="m-muted">sets completed</div>
        </div>
        <div>
          <div className="m-summary-big">{formatDuration(s.active_ms)}</div>
          <div className="m-muted">exercise time</div>
        </div>
      </div>

      <table className="m-sets">
        <thead>
          <tr>
            <th>Set</th>
            <th>Reps</th>
            <th>Time</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {s.sets.map((r) => (
            <tr key={r.number}>
              <td>{r.number}</td>
              <td>
                {r.reps} / {view.plan.reps_per_set}
              </td>
              <td>{formatDuration(r.active_ms)}</td>
              <td className="m-muted">{r.ended_early ? 'ended early' : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <ul className="m-summary-notes">
        {s.peak_deg && joint && (
          <li>
            Furthest {joint} per repetition: {Math.round(s.peak_deg.min_deg)}°–{Math.round(s.peak_deg.max_deg)}° (average{' '}
            {Math.round(s.peak_deg.mean_deg)}°)
          </li>
        )}
        {s.mean_rep_ms !== null && <li>Average repetition time: {(s.mean_rep_ms / 1000).toFixed(1)} s</li>}
        {uncounted && <li>{uncounted}</li>}
        {s.top_corrections.length > 0 && (
          <li>
            Most frequent reminders:{' '}
            {s.top_corrections.map((c) => `“${c.text}” ×${c.count}`).join(', ')}
          </li>
        )}
      </ul>

      <p className="m-fine">
        Angles and counts are camera estimates, not clinical measurements. Share questions about your exercises with your
        physical therapist.
      </p>

      <div className="m-summary-actions">
        <button className="m-btn m-btn-primary" onClick={() => void controls.dismiss()} disabled={controls.busy}>
          Done
        </button>
        <button className="m-btn" onClick={repeat} disabled={controls.busy}>
          Repeat session
        </button>
      </div>
      {controls.error && (
        <p className="m-error" role="alert">
          {controls.error}
        </p>
      )}
    </section>
  )
}
