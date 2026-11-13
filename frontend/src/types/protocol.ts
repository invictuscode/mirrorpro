// Mirrors backend/app/schemas/messages.py. See docs/PROTOCOL.md.

export const PROTOCOL_VERSION = 8

export type PipelineState = 'stopped' | 'starting' | 'running' | 'stopping' | 'error'

export type ErrorCode =
  | 'model_missing'
  | 'detector_init_failed'
  | 'camera_open_failed'
  | 'camera_read_failed'
  | 'inference_failed'

export interface ErrorInfo {
  code: ErrorCode
  message: string
}

export interface StatusMessage {
  type: 'status'
  protocol_version: number
  state: PipelineState
  error: ErrorInfo | null
  camera: string | null
  model: string
  profile: string
  preview_enabled: boolean
  angle_space: 'world' | 'image'
}

/** [x, y, z, visibility, presence]; x/y normalized to the source image. */
export type Landmark = [number, number, number, number, number]

export interface FrameMetrics {
  capture_fps: number
  inference_fps: number
  inference_ms: number
  latency_ms: number
  dropped_frames: number
}

export type AngleStatus = 'ok' | 'no_person' | 'low_visibility' | 'out_of_frame' | 'degenerate' | 'unavailable'

/** Experimental joint-angle estimate. `value_deg` is null unless status is 'ok'. */
export interface AngleMeasurement {
  id: string
  status: AngleStatus
  value_deg: number | null
  raw_deg: number | null
  confidence: number | null
}

export interface AngleDefinition {
  id: string
  label: string
  joint: string
  side: 'left' | 'right'
  landmarks: [number, number, number]
  convention: 'included' | 'flexion'
  description: string
}

export type RepPhase = 'waiting_for_start' | 'ready' | 'moving' | 'at_target' | 'returning'

export type RepEventKind =
  | 'rep_completed'
  | 'target_not_reached'
  | 'hold_too_short'
  | 'too_fast'
  | 'timed_out'
  | 'tracking_lost'
  | 'form_broken'
  | 'form_unverified'

export interface RepEvent {
  seq: number
  kind: RepEventKind
  timestamp_ms: number
  peak_deg: number | null
  duration_ms: number | null
  hold_ms: number | null
  /** For form_broken: the id of the broken rule. */
  detail: string | null
}

export type FeedbackCategory = 'tracking' | 'correction' | 'cue' | 'positive'

export interface FeedbackMessage {
  seq: number
  /** Message key, 'event:<key>' for rep outcomes, or 'rule:<id>' for form rules. */
  key: string
  text: string
  category: FeedbackCategory
  issued_ms: number
}

export type RuleState = 'inactive' | 'ok' | 'violated' | 'uncertain'

export interface RuleStatus {
  id: string
  state: RuleState
  value_deg: number | null
  sustained: boolean
  blocks_rep: boolean
  /** Why it is violated: outside its angle bounds, or bent toward/away from the camera. */
  reason: 'angle' | 'out_of_plane' | null
}

export interface FeedbackState {
  message: FeedbackMessage | null
  rules: RuleStatus[]
  /** False while the driving angle is unreliable: no judgements are made. */
  tracking_ok: boolean
}

export interface ExerciseState {
  exercise_id: string
  /** Changes whenever the exercise is selected or reset, from any client. */
  selection_id: number
  side: Side | null
  sides_used: Side[]
  phase: RepPhase
  reps: number
  signal_deg: number | null
  progress: number | null
  hold_ms: number
  last_event: RepEvent | null
  feedback: FeedbackState
}

export interface FrameMessage {
  type: 'frame'
  frame_id: number
  timestamp_ms: number
  width: number
  height: number
  person_detected: boolean
  landmarks: Landmark[] | null
  has_preview: boolean
  angle_space: 'world' | 'image'
  angles: AngleMeasurement[]
  exercise: ExerciseState | null
  metrics: FrameMetrics
}

export interface Topology {
  landmark_names: string[]
  connections: [number, number][]
}

export const LM_VISIBILITY = 3

// ---- Exercises (REST) ------------------------------------------------------

export type Side = 'left' | 'right'
export type CameraView = 'front' | 'side'
export type SideMode = 'single' | 'mean_of_visible'

export interface ExerciseSummary {
  id: string
  version: number
  name: string
  description: string
  camera_view: CameraView
  side_mode: SideMode
  default_side: Side | null
  dosage: { reps_per_set: number | null; sets: number | null }
  is_demo: boolean
}

export interface RepCountingConfig {
  start_deg: number
  target_deg: number
  hysteresis_deg: number
  confirm_ms: number
  min_hold_ms: number
  min_rep_ms: number
  max_rep_ms: number
  max_signal_gap_ms: number
}

export interface RepCountingOverrides {
  start_deg?: number
  target_deg?: number
  min_hold_ms?: number
}

export interface ExerciseDefinition {
  id: string
  version: number
  name: string
  description: string
  instructions: string[]
  camera: { view: CameraView; angle_space: 'world' | 'image'; guidance: string }
  relevant_landmarks: string[]
  display_angles: string[]
  signal: { joint: string; side_mode: SideMode; default_side: Side | null }
  rep_counting: RepCountingConfig
  dosage: { reps_per_set: number | null; sets: number | null }
  feedback: FeedbackConfig
  guidance: Guidance
  safety_notes: string[]
  clinical_review: { status: 'unreviewed_demo' | 'approved'; reviewed_by: string | null; note: string | null }
  reference_demonstration: string | null
}

export interface ActiveExercise {
  selection_id: number
  exercise: ExerciseDefinition
  side: Side | null
  overrides: RepCountingOverrides
  effective_rep_counting: RepCountingConfig
}

export interface FormRule {
  id: string
  joint: string
  side: 'signal' | 'left' | 'right' | 'both'
  phases: RepPhase[]
  min_deg: number | null
  max_deg: number | null
  sustain_ms: number
  message: string
  /** Breaking this rule (or hiding its joint) stops the rep counting. */
  blocks_rep: boolean
  /** Flag a bend toward/away from the camera when the distal segment looks
   * shorter than this fraction of its start-position length ratio. */
  out_of_plane_limit: number | null
}

export interface Guidance {
  setup: string[]
  cues: { start: string; move: string; hold: string; back: string }
  key_points: string[]
  tempo: string | null
}

export interface FeedbackConfig {
  cooldown_ms: number
  repeat_cooldown_ms: number
  display_ms: number
  min_display_ms: number
  tracking_grace_ms: number
  start_prompt_after_ms: number
  messages: Record<string, string>
  form_rules: FormRule[]
}

// ---- Sessions ---------------------------------------------------------------

export type SessionState = 'practice' | 'active' | 'resting' | 'paused' | 'completed' | 'ended'

export interface SetRecord {
  number: number
  reps: number
  active_ms: number
  ended_early: boolean
}

export interface SessionSummary {
  total_reps: number
  sets_completed: number
  sets: SetRecord[]
  active_ms: number
  elapsed_ms: number
  uncounted: Partial<Record<RepEventKind, number>>
  peak_deg: { min_deg: number; max_deg: number; mean_deg: number } | null
  mean_rep_ms: number | null
  feedback_counts: Partial<Record<FeedbackCategory, number>>
  top_corrections: { text: string; count: number }[]
}

export interface SessionView {
  session_id: number
  state: SessionState
  paused_from: 'practice' | 'active' | 'resting' | null
  exercise_id: string
  exercise_name: string
  exercise_version: number
  is_demo: boolean
  side: Side | null
  selection_id: number | null
  plan: { sets: number; reps_per_set: number; rest_s: number }
  /** Practice-rep status; null when the session started without one. */
  practice: 'pending' | 'completed' | 'skipped' | null
  /** Effective thresholds (preset + any custom settings). */
  rep_counting: RepCountingConfig
  /** Effective form rules (preset + session allowances). */
  form_rules: FormRule[]
  current_set: number
  current_set_reps: number
  sets: SetRecord[]
  active_ms: number
  rest_ms: number
  elapsed_ms: number
  rest_remaining_ms: number | null
  summary: SessionSummary | null
}

export interface SessionMessage {
  type: 'session'
  session: SessionView | null
}

export interface StartSessionRequest {
  exercise_id: string
  side?: Side | null
  overrides?: RepCountingOverrides
  sets?: number
  reps_per_set?: number
  rest_s?: number
  practice?: boolean
  rule_overrides?: Record<string, RuleOverride>
}

/** Per-session adjustment of one form rule. */
export interface RuleOverride {
  min_deg?: number | null
  max_deg?: number | null
  blocks_rep?: boolean
}
