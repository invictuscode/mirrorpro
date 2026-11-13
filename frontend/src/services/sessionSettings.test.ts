import { describe, expect, it } from 'vitest'

import type { ExerciseDefinition, FormRule } from '../types/protocol'
import { defaultsFor, describeThresholds, ruleErrors, ruleOverrides, toStartRequest, validateSettings } from './sessionSettings'

const def = (start: number, target: number, sideMode: 'single' | 'mean_of_visible' = 'single'): ExerciseDefinition =>
  ({
    id: 'ex',
    signal: { joint: 'elbow_flexion', side_mode: sideMode, default_side: sideMode === 'single' ? 'right' : null },
    rep_counting: {
      start_deg: start, target_deg: target, hysteresis_deg: 8, confirm_ms: 100, min_hold_ms: 1000,
      min_rep_ms: 800, max_rep_ms: 15000, max_signal_gap_ms: 750,
    },
    dosage: { sets: 2, reps_per_set: 10 },
  }) as ExerciseDefinition // partial fixture: only the fields these helpers read

describe('session settings', () => {
  it('derives defaults from the exercise', () => {
    expect(defaultsFor(def(35, 110))).toEqual({
      side: 'right', startDeg: 35, targetDeg: 110, holdS: 1, sets: 2, repsPerSet: 10, restS: 30,
    })
    expect(defaultsFor(def(35, 110, 'mean_of_visible')).side).toBeNull()
  })

  it('describes thresholds in the right direction', () => {
    expect(describeThresholds(def(35, 110), { startDeg: 35, targetDeg: 100 })).toEqual({
      start: 'Start position: elbow flexion at or below 35°',
      target: 'A repetition counts when elbow flexion reaches at least 100°',
    })
    expect(describeThresholds(def(70, 20), { startDeg: 70, targetDeg: 20 }).target).toContain('at most 20°')
  })

  it('accepts the defaults and rejects impossible settings', () => {
    const d = def(35, 110)
    expect(validateSettings(d, defaultsFor(d))).toEqual([])
    expect(validateSettings(d, { ...defaultsFor(d), targetDeg: 30 })).toEqual(
      expect.arrayContaining([expect.stringContaining('above the starting angle')]),
    )
    expect(validateSettings(d, { ...defaultsFor(d), targetDeg: 45 })[0]).toContain('more than 16° apart')
    expect(validateSettings(d, { ...defaultsFor(d), sets: 0 })).toEqual(['Sets must be 1–20.'])
    expect(validateSettings(d, { ...defaultsFor(d), holdS: 61 })).toHaveLength(1)
    // Decreasing exercise: the target must go down.
    const down = def(70, 20)
    expect(validateSettings(down, { ...defaultsFor(down), targetDeg: 80 })[0]).toContain('below the starting angle')
  })

  it('sends only changed thresholds as overrides', () => {
    const d = def(35, 110)
    expect(toStartRequest(d, defaultsFor(d))).toEqual({
      exercise_id: 'ex', side: 'right', sets: 2, reps_per_set: 10, rest_s: 30,
    })
    expect(toStartRequest(d, { ...defaultsFor(d), targetDeg: 95, holdS: 2.5 }).overrides).toEqual({
      target_deg: 95, min_hold_ms: 2500,
    })
  })
})

describe('rule allowances', () => {
  const elbow: FormRule = {
    id: 'elbows_straight', joint: 'elbow_flexion', side: 'both', phases: ['moving'], min_deg: null, max_deg: 45,
    sustain_ms: 400, message: 'Keep your elbows fairly straight.', blocks_rep: true, out_of_plane_limit: 0.45,
  }
  it('sends only changed allowances', () => {
    expect(ruleOverrides([elbow], [elbow])).toEqual({})
    expect(ruleOverrides([elbow], [{ ...elbow, max_deg: 60, blocks_rep: false }])).toEqual({
      elbows_straight: { max_deg: 60, blocks_rep: false },
    })
  })
  it('explains invalid allowances', () => {
    expect(ruleErrors([elbow])).toEqual([])
    expect(ruleErrors([{ ...elbow, max_deg: 200 }])[0]).toContain('between 0° and 180°')
    expect(ruleErrors([{ ...elbow, min_deg: 50 }])[0]).toContain('lower limit')
  })
})
