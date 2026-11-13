import type { FeedbackMessage, FormRule, RuleState } from '../types/protocol'

export const RULE_STATE_LABEL: Record<RuleState, string> = {
  inactive: 'not checked now',
  ok: 'within range',
  violated: 'outside range',
  uncertain: 'not tracked — no judgement',
}

export function describeRuleBounds(rule: FormRule): string {
  if (rule.min_deg !== null && rule.max_deg !== null) return `${rule.min_deg}°–${rule.max_deg}°`
  if (rule.max_deg !== null) return `≤ ${rule.max_deg}°`
  return `≥ ${rule.min_deg ?? 0}°`
}

/** Append `message` to a newest-first log if it is new (by seq). */
export function appendToLog(log: FeedbackMessage[], message: FeedbackMessage | null, limit = 8): FeedbackMessage[] {
  if (!message || log.some((m) => m.seq === message.seq)) return log
  return [message, ...log].slice(0, limit)
}
