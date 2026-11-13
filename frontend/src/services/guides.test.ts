import { describe, expect, it } from 'vitest'

import { buildGuides, buildHighlights, currentCue } from './guides'
import type { AngleDefinition, ExerciseDefinition, ExerciseState, RepCountingConfig } from '../types/protocol'

const angleDefs: AngleDefinition[] = (['left', 'right'] as const).flatMap((side, k) => [
  { id: `${side}_elbow_flexion`, label: '', joint: 'elbow_flexion', side, landmarks: [11 + k, 13 + k, 15 + k], convention: 'flexion', description: '' },
  { id: `${side}_shoulder_elevation`, label: '', joint: 'shoulder_elevation', side, landmarks: [23 + k, 11 + k, 13 + k], convention: 'included', description: '' },
])

const def = {
  signal: { joint: 'shoulder_elevation', side_mode: 'mean_of_visible', default_side: null },
  feedback: {
    form_rules: [{ id: 'elbows_straight', joint: 'elbow_flexion', side: 'both', phases: ['moving'], min_deg: null, max_deg: 30, sustain_ms: 400, message: '', blocks_rep: true, out_of_plane_limit: 0.6 }],
  },
} as unknown as ExerciseDefinition // partial fixture: only the fields these helpers read

const rc: RepCountingConfig = {
  start_deg: 30, target_deg: 140, hysteresis_deg: 8, confirm_ms: 100, min_hold_ms: 1000,
  min_rep_ms: 800, max_rep_ms: 15000, max_signal_gap_ms: 750,
}

const live = (phase: ExerciseState['phase'], holdMs = 0): ExerciseState => ({
  exercise_id: 'x', selection_id: 1, side: null, sides_used: ['left', 'right'], phase, reps: 0,
  signal_deg: 50, progress: 0.2, hold_ms: holdMs, last_event: null,
  feedback: { message: null, tracking_ok: true, rules: [{ id: 'elbows_straight', state: 'violated', value_deg: 60, sustained: true, blocks_rep: true, reason: 'angle' }] },
})

describe('guides', () => {
  it('guides the driving joint on every side in use', () => {
    const g = buildGuides(def, angleDefs, rc, live('moving'), null)
    expect(g).toHaveLength(2)
    expect(g[0]).toMatchObject({ convention: 'included', startDeg: 30, targetDeg: 140, mode: 'to_target' })
    expect(g.map((x) => x.landmarks[1]).sort()).toEqual([11, 12])
  })

  it('switches to hold, then back toward the start', () => {
    expect(buildGuides(def, angleDefs, rc, live('at_target', 300), null)[0]?.mode).toBe('hold')
    expect(buildGuides(def, angleDefs, rc, live('at_target', 1200), null)[0]?.mode).toBe('to_start')
  })

  it('rings the steady joints with their rule state', () => {
    const h = buildHighlights(def, angleDefs, live('moving'), null)
    expect(h).toEqual([
      { landmark: 13, state: 'violated' },
      { landmark: 14, state: 'violated' },
    ])
  })

  it('picks the coaching cue for the phase', () => {
    expect(currentCue(live('waiting_for_start'), 1000)).toBe('start')
    expect(currentCue(live('moving'), 1000)).toBe('move')
    expect(currentCue(live('at_target', 200), 1000)).toBe('hold')
    expect(currentCue(live('at_target', 1500), 1000)).toBe('back')
    expect(currentCue(null, 0)).toBe('start')
  })
})
