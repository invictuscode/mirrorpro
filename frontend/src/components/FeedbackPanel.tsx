import { useEffect, useState } from 'react'

import { Panel } from './Panels'
import { RULE_STATE_LABEL, appendToLog, describeRuleBounds } from '../services/feedback'
import type { ActiveExercise, ExerciseState, FeedbackMessage } from '../types/protocol'

/** Developer view of the feedback engine: rule states, tracking gate, and a
 * log of recent messages. */
export function FeedbackPanel({ active, live }: { active: ActiveExercise | null; live: ExerciseState | null }) {
  const [log, setLog] = useState<FeedbackMessage[]>([])
  const state = active && live?.selection_id === active.selection_id ? live.feedback : null

  useEffect(() => setLog([]), [active?.selection_id])
  useEffect(() => setLog((l) => appendToLog(l, state?.message ?? null)), [state?.message])

  if (!active) return null
  const rules = active.exercise.feedback.form_rules
  const byId = new Map((state?.rules ?? []).map((r) => [r.id, r]))

  return (
    <Panel title="Feedback rules">
      <div className="row">
        <span className="row-label">Judgements</span>
        <span className={`row-value ${state?.tracking_ok === false ? 'warn' : 'ok'}`}>
          {state ? (state.tracking_ok ? 'active' : 'paused — tracking unreliable') : '—'}
        </span>
      </div>
      {rules.length === 0 && <p className="hint">No form rules configured for this exercise.</p>}
      <ul className="rule-list">
        {rules.map((rule) => {
          const s = byId.get(rule.id)
          return (
            <li key={rule.id} className={`rule rule-${s?.state ?? 'inactive'}`}>
              <div className="rule-head">
                <span>{rule.message}</span>
                <span className="rule-value">{s?.value_deg != null ? `${Math.round(s.value_deg)}°` : ''}</span>
              </div>
              <div className="hint">
                {rule.joint.replaceAll('_', ' ')} ({rule.side}) {describeRuleBounds(rule)} · during{' '}
                {rule.phases.join(', ').replaceAll('_', ' ')} · {s ? RULE_STATE_LABEL[s.state] : '—'}
                {s?.reason === 'out_of_plane' ? ' (bent toward/away from camera)' : ''}
                {rule.blocks_rep ? ' · blocks reps' : ''}
              </div>
            </li>
          )
        })}
      </ul>
      <h3 className="subhead">Recent messages</h3>
      {log.length === 0 ? (
        <p className="hint">None yet.</p>
      ) : (
        <ol className="fb-log">
          {log.map((m) => (
            <li key={m.seq} className={`fb-${m.category}`}>
              <span className="fb-log-cat">{m.category}</span> {m.text}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}
