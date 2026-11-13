import { describe, expect, it } from 'vitest'

import type { AnalysisResult, SuggestedRule } from '../types/authoring'
import { basicsErrors, draftFromAnalysis, isSeriousWarning, newSteadyRule, parseInstructions, type Basics } from './authoring'

const basics: Basics = {
  name: ' Towel slide ',
  description: 'Slide the hand forward.',
  instructionsText: 'Sit side-on.\n\n  Slide forward, then back.  \n',
  cameraView: 'side',
  cameraGuidance: 'Sit side-on.',
}

const rule = (include: boolean): SuggestedRule => ({
  include,
  observed_range_deg: [10, 18],
  rule: {
    id: 'steady_shoulder_elevation', joint: 'shoulder_elevation', side: 'signal', phases: ['moving'],
    min_deg: null, max_deg: 35, sustain_ms: 500, message: 'Keep your shoulder elevation steady.', blocks_rep: true, out_of_plane_limit: 0.6,
  },
})

const analysis = (withThresholds = true): AnalysisResult => ({
  demo_id: 'd',
  joint_candidates: [],
  chosen: { joint: 'elbow_flexion', side_mode: 'single', side: 'left', range_deg: 100, valid_fraction: 1, score: 100 },
  increasing: true,
  rest_deg: 10,
  typical_peak_deg: 120,
  reps: [],
  suggested_rep_counting: withThresholds
    ? { start_deg: 40, target_deg: 105, hysteresis_deg: 8, confirm_ms: 100, min_hold_ms: 0, min_rep_ms: 800, max_rep_ms: 9000, max_signal_gap_ms: 750 }
    : null,
  suggested_rules: [],
  warnings: [],
  chart: null,
})

describe('authoring helpers', () => {
  it('parses instructions one per line', () => {
    expect(parseInstructions(basics.instructionsText)).toEqual(['Sit side-on.', 'Slide forward, then back.'])
  })

  it('requires the basics', () => {
    expect(basicsErrors(basics)).toEqual([])
    expect(basicsErrors({ ...basics, name: ' ', instructionsText: '\n' })).toHaveLength(2)
  })

  it('builds a draft from suggestions, including only ticked rules', () => {
    const d = draftFromAnalysis(basics, analysis(), [rule(true), { ...rule(false), rule: { ...rule(false).rule, id: 'other' } }])
    expect(d).toMatchObject({
      name: 'Towel slide', signal_joint: 'elbow_flexion', side_mode: 'single', default_side: 'left',
      rep_counting: { start_deg: 40, target_deg: 105 },
    })
    expect(d?.form_rules.map((r) => r.id)).toEqual(['steady_shoulder_elevation'])
    expect(draftFromAnalysis(basics, analysis(false), [])).toBeNull()
  })

  it('treats the single-demonstration note as a reminder, not a problem', () => {
    expect(isSeriousWarning('single_demonstration')).toBe(false)
    expect(isSeriousWarning('few_reps')).toBe(true)
  })
})

describe('newSteadyRule', () => {
  it('creates a blocking straight-joint rule with a unique id', () => {
    const r = newSteadyRule('elbow_flexion', [])
    expect(r).toMatchObject({ id: 'steady_elbow_flexion', max_deg: 45, blocks_rep: true, message: 'Keep your elbows straight.' })
    expect(newSteadyRule('elbow_flexion', [r]).id).toBe('steady_elbow_flexion_2')
  })
})
