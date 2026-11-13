import { guideMode } from './guideGeometry'
import type { GuideSpec, Highlight } from '../components/guideOverlay'
import type { AngleDefinition, ExerciseDefinition, ExerciseState, FormRule, RepCountingConfig, Side } from '../types/protocol'

function sidesOf(live: ExerciseState | null, side: Side | null): Side[] {
  if (live?.sides_used.length) return live.sides_used
  return side ? [side] : ['left', 'right']
}

/** Ghost limbs + direction arrow for the joint that drives the count. */
export function buildGuides(
  def: ExerciseDefinition,
  angleDefs: AngleDefinition[],
  rc: RepCountingConfig,
  live: ExerciseState | null,
  side: Side | null,
): GuideSpec[] {
  const sides = sidesOf(live, side)
  const mode = guideMode(live?.phase ?? 'waiting_for_start', live?.hold_ms ?? 0, rc.min_hold_ms)
  return angleDefs
    .filter((d) => d.joint === def.signal.joint && sides.includes(d.side))
    .map((d) => ({
      landmarks: d.landmarks,
      convention: d.convention,
      startDeg: rc.start_deg,
      targetDeg: rc.target_deg,
      mode,
    }))
}

function ruleSides(rule: FormRule, signalSides: Side[]): Side[] {
  if (rule.side === 'signal') return signalSides
  if (rule.side === 'both') return ['left', 'right']
  return [rule.side]
}

/** Rings on the joints that must stay steady, coloured by each rule's state. */
export function buildHighlights(
  def: ExerciseDefinition,
  angleDefs: AngleDefinition[],
  live: ExerciseState | null,
  side: Side | null,
): Highlight[] {
  const states = new Map((live?.feedback.rules ?? []).map((r) => [r.id, r.state]))
  const sides = sidesOf(live, side)
  const out: Highlight[] = []
  for (const rule of def.feedback.form_rules) {
    const state = states.get(rule.id) ?? 'inactive'
    for (const d of angleDefs) {
      if (d.joint === rule.joint && ruleSides(rule, sides).includes(d.side)) {
        out.push({ landmark: d.landmarks[1], state })
      }
    }
  }
  return out
}

export type CueKey = 'start' | 'move' | 'hold' | 'back'

/** Which coaching line applies right now. */
export function currentCue(live: ExerciseState | null, minHoldMs: number): CueKey {
  switch (live?.phase ?? 'waiting_for_start') {
    case 'waiting_for_start':
      return 'start'
    case 'ready':
    case 'moving':
      return 'move'
    case 'at_target':
      return (live?.hold_ms ?? 0) < minHoldMs ? 'hold' : 'back'
    case 'returning':
      return 'back'
  }
}
