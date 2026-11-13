import { DemoChart } from './DemoChart'
import { JOINT_LABEL, isSeriousWarning } from '../../services/authoring'
import type { AnalysisResult, AnalyzeRequest, DemonstrationInfo, SuggestedRule } from '../../types/authoring'

interface Props {
  demo: DemonstrationInfo
  analysis: AnalysisResult
  busy: boolean
  rules: SuggestedRule[]
  onRules: (rules: SuggestedRule[]) => void
  onReanalyze: (req: AnalyzeRequest) => void
  onNext: () => void
  onRedo: () => void
}

/** What the demonstration suggests — explicitly as suggestions, with the
 * evidence (chart, detected repetitions, warnings) to judge them. */
export function ReviewStep({ demo, analysis: a, busy, rules, onRules, onReanalyze, onNext, onRedo }: Props) {
  const serious = a.warnings.filter((w) => isSeriousWarning(w.code))
  const note = a.warnings.find((w) => !isSeriousWarning(w.code))
  const rc = a.suggested_rep_counting
  const chosenKey = a.chosen ? `${a.chosen.joint}|${a.chosen.side_mode}|${a.chosen.side ?? ''}` : ''

  return (
    <section className="t-step">
      <h2>3. Review what the demonstration suggests</h2>
      <p className="hint">
        {demo.source === 'live' ? 'Recorded' : 'Uploaded'} demonstration · {(demo.duration_ms / 1000).toFixed(1)} s ·{' '}
        {demo.frames} frames · person visible in {Math.round(demo.person_fraction * 100)}%
      </p>
      {note && <p className="t-note">{note.message}</p>}
      {serious.length > 0 && (
        <ul className="t-warnings" role="alert">
          {serious.map((w) => (
            <li key={w.code}>{w.message}</li>
          ))}
        </ul>
      )}

      {a.chart && a.chosen && (
        <DemoChart
          title={`${JOINT_LABEL[a.chosen.joint] ?? a.chosen.joint}${a.chosen.side ? ` (${a.chosen.side})` : ' (both sides)'} during the demonstration`}
          tMs={a.chart.t_ms}
          deg={a.chart.deg}
          reps={a.reps}
          startDeg={rc?.start_deg ?? null}
          targetDeg={rc?.target_deg ?? null}
        />
      )}

      <div className="t-columns">
        <div>
          <h3 className="subhead">Joint that drives the count</h3>
          {a.joint_candidates.length === 0 && <p className="hint">No joint moved clearly.</p>}
          {a.joint_candidates.map((c) => {
            const key = `${c.joint}|${c.side_mode}|${c.side ?? ''}`
            return (
              <label key={key} className="t-radio-row">
                <input
                  type="radio"
                  name="joint"
                  checked={key === chosenKey}
                  disabled={busy}
                  onChange={() => onReanalyze({ joint: c.joint, side_mode: c.side_mode, side: c.side })}
                />
                {JOINT_LABEL[c.joint] ?? c.joint} — {c.side ?? 'both sides'} · range {Math.round(c.range_deg)}° · tracked{' '}
                {Math.round(c.valid_fraction * 100)}%
              </label>
            )
          })}
          <h3 className="subhead">Start position</h3>
          <div className="segmented">
            {(['low', 'high'] as const).map((p) => (
              <label key={p}>
                <input
                  type="radio"
                  name="start-pos"
                  disabled={busy || a.increasing === null}
                  checked={a.increasing === null ? false : (p === 'low') === a.increasing}
                  onChange={() =>
                    onReanalyze({
                      start_position: p,
                      ...(a.chosen ? { joint: a.chosen.joint, side_mode: a.chosen.side_mode, side: a.chosen.side } : {}),
                    })
                  }
                />
                {p === 'low' ? 'Low end of the range' : 'High end of the range'}
              </label>
            ))}
          </div>
        </div>
        <div>
          <h3 className="subhead">Detected repetitions ({a.reps.length})</h3>
          {a.reps.length > 0 ? (
            <table className="t-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Furthest angle</th>
                  <th>Duration</th>
                  <th>Time near the end position</th>
                </tr>
              </thead>
              <tbody>
                {a.reps.map((r, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{r.peak_deg.toFixed(0)}°</td>
                    <td>{((r.end_ms - r.start_ms) / 1000).toFixed(1)} s</td>
                    <td>{(r.hold_ms / 1000).toFixed(1)} s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="hint">None found.</p>
          )}
          {rc && (
            <p className="hint">
              Suggested: start {rc.start_deg}°, target {rc.target_deg}°
              {rc.min_hold_ms ? `, hold ${rc.min_hold_ms / 1000} s` : ''}. The target is set a little short of the
              demonstration's typical {a.typical_peak_deg?.toFixed(0)}°, because a demonstration is usually fuller
              than a patient needs. You can change every value in the next step.
            </p>
          )}
        </div>
      </div>

      {rules.length > 0 && (
        <>
          <h3 className="subhead">Joints that must stay steady</h3>
          <p className="hint">
            These joints barely moved in your demonstration, so the patient must keep them steady too. Otherwise the
            movement could be imitated with another joint (for example bending the elbows during an arm raise). They
            are on by default; untick any that should be free to move.
          </p>
          {rules.map((s, i) => {
            const set = (patch: Partial<SuggestedRule>) => onRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)))
            return (
              <div key={s.rule.id} className="t-steady">
                <label className="t-radio-row">
                  <input type="checkbox" checked={s.include} onChange={(e) => set({ include: e.target.checked })} />
                  <span>
                    <strong>{s.rule.message}</strong> {JOINT_LABEL[s.rule.joint] ?? s.rule.joint} stayed between{' '}
                    {s.observed_range_deg[0].toFixed(0)}° and {s.observed_range_deg[1].toFixed(0)}°; allowed{' '}
                    {s.rule.min_deg !== null ? `${s.rule.min_deg}°` : '0°'}–{s.rule.max_deg !== null ? `${s.rule.max_deg}°` : '180°'}.
                  </span>
                </label>
                {s.include && (
                  <label className="t-radio-row t-indent">
                    <input
                      type="checkbox"
                      checked={s.rule.blocks_rep}
                      onChange={(e) => set({ rule: { ...s.rule, blocks_rep: e.target.checked } })}
                    />
                    Don&apos;t count repetitions that break this (otherwise it is only a reminder)
                  </label>
                )}
              </div>
            )
          })}
        </>
      )}

      <div className="button-row">
        <button className="btn btn-primary" onClick={onNext} disabled={busy || !rc}>
          Next: edit parameters
        </button>
        <button className="btn btn-ghost" onClick={onRedo} disabled={busy}>
          Record again
        </button>
      </div>
      {!rc && <p className="hint">No usable thresholds were found; record the demonstration again.</p>}
    </section>
  )
}
