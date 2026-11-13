import { describe, expect, it } from 'vitest'

import type { RepEvent } from '../types/protocol'
import { describeRepEvent, describeUncounted, phaseLabel } from './exercise'

const event = (kind: RepEvent['kind'], peak: number | null = 112.4): RepEvent => ({
  seq: 1,
  kind,
  timestamp_ms: 0,
  peak_deg: peak,
  duration_ms: 1500,
  hold_ms: 0,
  detail: null,
})

describe('exercise display helpers', () => {
  it('describes counted and rejected reps with their peak', () => {
    expect(describeRepEvent(event('rep_completed'))).toEqual({ counted: true, text: 'Repetition counted (furthest 112°)' })
    const partial = describeRepEvent(event('target_not_reached', 87.6))
    expect(partial.counted).toBe(false)
    expect(partial.text).toContain('88°')
    expect(describeRepEvent(event('tracking_lost', null)).text).not.toContain('°')
  })

  it('labels every phase', () => {
    expect(phaseLabel('waiting_for_start')).toBe('Move to the start position')
    expect(phaseLabel('at_target')).toBe('At target')
  })
})

describe('describeUncounted', () => {
  it('summarises reasons, most frequent first', () => {
    expect(describeUncounted({})).toBeNull()
    expect(describeUncounted({ tracking_lost: 1, target_not_reached: 2 })).toBe(
      '3 not counted: target not reached ×2, tracking lost ×1',
    )
  })
})
