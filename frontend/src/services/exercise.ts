import type { RepEvent, RepPhase } from '../types/protocol'

const PHASE_LABEL: Record<RepPhase, string> = {
  waiting_for_start: 'Move to the start position',
  ready: 'Ready',
  moving: 'Moving',
  at_target: 'At target',
  returning: 'Returning',
}

export function phaseLabel(phase: RepPhase): string {
  return PHASE_LABEL[phase]
}

/** Factual description of how the counter judged the last attempt. These are
 * counting diagnostics, not movement advice. */
export function describeRepEvent(e: RepEvent): { counted: boolean; text: string } {
  const peak = e.peak_deg === null ? '' : ` (furthest ${Math.round(e.peak_deg)}°)`
  switch (e.kind) {
    case 'rep_completed':
      return { counted: true, text: `Repetition counted${peak}` }
    case 'target_not_reached':
      return { counted: false, text: `Not counted: target angle not reached${peak}` }
    case 'hold_too_short':
      return { counted: false, text: 'Not counted: target position not held long enough' }
    case 'too_fast':
      return { counted: false, text: 'Not counted: faster than the minimum repetition time' }
    case 'timed_out':
      return { counted: false, text: 'Not counted: longer than the maximum repetition time' }
    case 'tracking_lost':
      return { counted: false, text: 'Not counted: tracking was lost during the repetition' }
    case 'form_broken':
      return { counted: false, text: `Not counted: a joint that must stay steady moved (${e.detail ?? 'rule'})` }
    case 'form_unverified':
      return { counted: false, text: 'Not counted: a joint that must stay steady was not visible' }
  }
}

const UNCOUNTED_LABEL: Record<Exclude<RepEvent['kind'], 'rep_completed'>, string> = {
  target_not_reached: 'target not reached',
  hold_too_short: 'not held long enough',
  too_fast: 'faster than the minimum time',
  timed_out: 'took longer than the maximum time',
  tracking_lost: 'tracking lost',
  form_broken: 'a steady joint moved',
  form_unverified: 'a steady joint was not visible',
}

/** "3 not counted: target not reached ×2, tracking lost ×1", or null if none. */
export function describeUncounted(counts: Partial<Record<RepEvent['kind'], number>>): string | null {
  const parts = Object.entries(counts)
    .filter(([kind, n]) => kind !== 'rep_completed' && (n ?? 0) > 0)
    .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    .map(([kind, n]) => `${UNCOUNTED_LABEL[kind as keyof typeof UNCOUNTED_LABEL] ?? kind} ×${n}`)
  if (parts.length === 0) return null
  const total = Object.entries(counts).reduce((sum, [k, n]) => sum + (k === 'rep_completed' ? 0 : (n ?? 0)), 0)
  return `${total} not counted: ${parts.join(', ')}`
}
