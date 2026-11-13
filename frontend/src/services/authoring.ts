import type { AnalysisResult, DraftFields, SuggestedRule } from '../types/authoring'
import type { CameraView, FormRule } from '../types/protocol'

export const JOINT_LABEL: Record<string, string> = {
  elbow_flexion: 'Elbow flexion',
  shoulder_elevation: 'Shoulder elevation',
  hip_flexion: 'Hip flexion',
  knee_flexion: 'Knee flexion',
}

export interface Basics {
  name: string
  description: string
  instructionsText: string
  cameraView: CameraView
  cameraGuidance: string
}

/** One instruction per non-empty line. */
export function parseInstructions(text: string): string[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
}

export function basicsErrors(b: Basics): string[] {
  const errors: string[] = []
  if (!b.name.trim()) errors.push('Enter a name.')
  if (!b.description.trim()) errors.push('Enter a short description.')
  if (parseInstructions(b.instructionsText).length === 0) errors.push('Enter at least one instruction.')
  if (!b.cameraGuidance.trim()) errors.push('Describe where the patient should stand relative to the camera.')
  return errors
}

/** Starting draft from the therapist's basics and the analysis suggestions.
 * Only rules the therapist ticked are included. Returns null when the
 * analysis produced no usable thresholds (the therapist must record again or
 * enter them manually). */
export function draftFromAnalysis(b: Basics, a: AnalysisResult, rules: SuggestedRule[]): DraftFields | null {
  if (!a.chosen || !a.suggested_rep_counting) return null
  return {
    name: b.name.trim(),
    description: b.description.trim(),
    instructions: parseInstructions(b.instructionsText),
    camera_view: b.cameraView,
    camera_guidance: b.cameraGuidance.trim(),
    angle_space: 'image',
    signal_joint: a.chosen.joint,
    side_mode: a.chosen.side_mode,
    default_side: a.chosen.side_mode === 'single' ? (a.chosen.side ?? 'right') : null,
    rep_counting: a.suggested_rep_counting,
    dosage: { sets: 2, reps_per_set: 10 },
    target_not_reached_message: null,
    form_rules: rules.filter((r) => r.include).map((r) => r.rule),
  }
}

/** Warnings that undermine the suggestions vs. the standing reminder. */
export function isSeriousWarning(code: string): boolean {
  return code !== 'single_demonstration'
}

const STEADY_DEFAULT_TEXT: Record<string, string> = {
  elbow_flexion: 'Keep your elbows straight.',
  knee_flexion: 'Keep your knees straight.',
  shoulder_elevation: 'Keep your upper arms by your sides.',
  hip_flexion: 'Keep your body upright.',
}

/** A "must stay steady" rule a therapist adds by hand (e.g. when the
 * demonstration did not keep that joint still enough for it to be suggested).
 * Defaults: held near straight (≤ 30°), checked during the whole movement,
 * blocks repetitions, with the out-of-plane check on. All editable. */
export function newSteadyRule(joint: string, existing: FormRule[]): FormRule {
  const base = `steady_${joint}`
  let id = base
  for (let n = 2; existing.some((r) => r.id === id); n++) id = `${base}_${n}`
  return {
    id,
    joint,
    side: 'signal',
    phases: ['moving', 'at_target', 'returning'],
    min_deg: null,
    max_deg: 45,
    sustain_ms: 400,
    message: STEADY_DEFAULT_TEXT[joint] ?? 'Keep this joint steady.',
    blocks_rep: true,
    out_of_plane_limit: 0.45,
  }
}
