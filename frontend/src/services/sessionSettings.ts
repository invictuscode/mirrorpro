import type { ExerciseDefinition, FormRule, RepCountingOverrides, RuleOverride, Side, StartSessionRequest } from '../types/protocol'

/** Editable start-of-session settings (seconds in the UI, ms on the wire). */
export interface SettingsDraft {
  side: Side | null
  startDeg: number
  targetDeg: number
  holdS: number
  sets: number
  repsPerSet: number
  restS: number
}

export const DEFAULT_REST_S = 30
export const LIMITS = {
  angle: { min: 0, max: 180, step: 5 },
  holdS: { min: 0, max: 60, step: 0.5 },
  sets: { min: 1, max: 20, step: 1 },
  repsPerSet: { min: 1, max: 200, step: 1 },
  restS: { min: 0, max: 600, step: 5 },
} as const

export function defaultsFor(def: ExerciseDefinition): SettingsDraft {
  return {
    side: def.signal.side_mode === 'single' ? (def.signal.default_side ?? 'right') : null,
    startDeg: def.rep_counting.start_deg,
    targetDeg: def.rep_counting.target_deg,
    holdS: def.rep_counting.min_hold_ms / 1000,
    sets: def.dosage.sets ?? 1,
    repsPerSet: def.dosage.reps_per_set ?? 10,
    restS: DEFAULT_REST_S,
  }
}

/** Plain-language meaning of the thresholds for this exercise. */
export function describeThresholds(def: ExerciseDefinition, d: Pick<SettingsDraft, 'startDeg' | 'targetDeg'>) {
  const joint = def.signal.joint.replaceAll('_', ' ')
  const up = def.rep_counting.target_deg > def.rep_counting.start_deg
  return {
    start: `Start position: ${joint} ${up ? 'at or below' : 'at or above'} ${d.startDeg}°`,
    target: `A repetition counts when ${joint} reaches ${up ? 'at least' : 'at most'} ${d.targetDeg}°`,
  }
}

/** Same rules the backend enforces, checked before starting so problems are
 * explained here rather than as a failed request. */
export function validateSettings(def: ExerciseDefinition, d: SettingsDraft): string[] {
  const errors: string[] = []
  const inRange = (v: number, l: { min: number; max: number }) => Number.isFinite(v) && v >= l.min && v <= l.max
  if (!inRange(d.startDeg, LIMITS.angle) || !inRange(d.targetDeg, LIMITS.angle)) {
    errors.push('Angles must be between 0° and 180°.')
  }
  const up = def.rep_counting.target_deg > def.rep_counting.start_deg
  if (up ? d.targetDeg <= d.startDeg : d.targetDeg >= d.startDeg) {
    errors.push(`The target must be ${up ? 'above' : 'below'} the starting angle for this exercise.`)
  }
  const minGap = 2 * def.rep_counting.hysteresis_deg
  if (Math.abs(d.targetDeg - d.startDeg) <= minGap) {
    errors.push(`Start and target must be more than ${minGap}° apart so small wobbles are not counted.`)
  }
  if (!inRange(d.holdS, LIMITS.holdS)) errors.push(`Hold time must be 0–${LIMITS.holdS.max} seconds.`)
  if (!Number.isInteger(d.sets) || !inRange(d.sets, LIMITS.sets)) errors.push(`Sets must be 1–${LIMITS.sets.max}.`)
  if (!Number.isInteger(d.repsPerSet) || !inRange(d.repsPerSet, LIMITS.repsPerSet)) {
    errors.push(`Repetitions per set must be 1–${LIMITS.repsPerSet.max}.`)
  }
  if (!inRange(d.restS, LIMITS.restS)) errors.push(`Rest must be 0–${LIMITS.restS.max} seconds.`)
  return errors
}

/** Request for these settings; thresholds are sent as overrides only when they
 * differ from the exercise's defaults. */
export function toStartRequest(def: ExerciseDefinition, d: SettingsDraft): StartSessionRequest {
  const base = defaultsFor(def)
  const overrides: RepCountingOverrides = {}
  if (d.startDeg !== base.startDeg) overrides.start_deg = d.startDeg
  if (d.targetDeg !== base.targetDeg) overrides.target_deg = d.targetDeg
  if (d.holdS !== base.holdS) overrides.min_hold_ms = Math.round(d.holdS * 1000)
  return {
    exercise_id: def.id,
    side: d.side,
    sets: d.sets,
    reps_per_set: d.repsPerSet,
    rest_s: d.restS,
    ...(Object.keys(overrides).length ? { overrides } : {}),
  }
}

/** Only the form-rule fields that differ from the exercise's own rules. */
export function ruleOverrides(original: FormRule[], edited: FormRule[]): Record<string, RuleOverride> {
  const out: Record<string, RuleOverride> = {}
  for (const e of edited) {
    const o = original.find((r) => r.id === e.id)
    if (!o) continue
    const diff: RuleOverride = {}
    if (e.min_deg !== o.min_deg) diff.min_deg = e.min_deg
    if (e.max_deg !== o.max_deg) diff.max_deg = e.max_deg
    if (e.blocks_rep !== o.blocks_rep) diff.blocks_rep = e.blocks_rep
    if (Object.keys(diff).length) out[e.id] = diff
  }
  return out
}

/** Problems with edited allowances, explained before starting. */
export function ruleErrors(rules: FormRule[]): string[] {
  return rules.flatMap((r) => {
    const bad = (v: number | null) => v !== null && (!Number.isFinite(v) || v < 0 || v > 180)
    if (bad(r.min_deg) || bad(r.max_deg)) return [`“${r.message}”: allowances must be between 0° and 180°.`]
    if (r.min_deg !== null && r.max_deg !== null && r.min_deg >= r.max_deg) {
      return [`“${r.message}”: the lower limit must be below the upper limit.`]
    }
    return []
  })
}
