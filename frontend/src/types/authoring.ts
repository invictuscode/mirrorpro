// Mirrors backend/app/schemas/authoring.py. See docs/CUSTOM_EXERCISES.md.
import type { CameraView, FormRule, RepCountingConfig, Side, SideMode } from './protocol'

export interface DemonstrationInfo {
  demo_id: string
  source: 'live' | 'upload'
  angle_space: 'image' | 'world'
  duration_ms: number
  frames: number
  person_fraction: number
}

export interface LiveRecordingStatus {
  recording: boolean
  elapsed_ms: number
  frames: number
  max_ms: number
}

export interface JointCandidate {
  joint: string
  side_mode: SideMode
  side: Side | null
  range_deg: number
  valid_fraction: number
  score: number
}

export interface DetectedRep {
  start_ms: number
  end_ms: number
  peak_deg: number
  hold_ms: number
}

export interface AnalysisWarning {
  code: string
  message: string
}

export interface SuggestedRule {
  include: boolean
  rule: FormRule
  observed_range_deg: [number, number]
}

export interface AnalysisResult {
  demo_id: string
  joint_candidates: JointCandidate[]
  chosen: JointCandidate | null
  increasing: boolean | null
  rest_deg: number | null
  typical_peak_deg: number | null
  reps: DetectedRep[]
  suggested_rep_counting: RepCountingConfig | null
  suggested_rules: SuggestedRule[]
  warnings: AnalysisWarning[]
  chart: { t_ms: number[]; deg: (number | null)[] } | null
}

export interface AnalyzeRequest {
  joint?: string
  side_mode?: SideMode
  side?: Side | null
  start_position?: 'low' | 'high'
}

export interface DraftFields {
  name: string
  description: string
  instructions: string[]
  camera_view: CameraView
  camera_guidance: string
  angle_space: 'image' | 'world'
  signal_joint: string
  side_mode: SideMode
  default_side: Side | null
  rep_counting: RepCountingConfig
  dosage: { reps_per_set: number | null; sets: number | null }
  target_not_reached_message: string | null
  form_rules: FormRule[]
}

export interface DemonstrationRecord {
  demo_id: string
  source: 'live' | 'upload'
  duration_ms: number
  frames: number
  angle_data_stored: boolean
}

export interface CustomExercise {
  id: string
  status: 'draft' | 'approved' | 'archived'
  version: number
  fields: DraftFields
  demonstrations: DemonstrationRecord[]
  created_at: string
  updated_at: string
  approved_by: string | null
  approved_at: string | null
  live_version: number | null
}
