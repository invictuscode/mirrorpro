import { describe, expect, it } from 'vitest'

import type { FeedbackMessage, FormRule } from '../types/protocol'
import { appendToLog, describeRuleBounds } from './feedback'

const msg = (seq: number): FeedbackMessage => ({
  seq,
  key: 'rule:x',
  text: 'Keep your upper arm still.',
  category: 'correction',
  issued_ms: seq * 1000,
})

const rule = (min: number | null, max: number | null): FormRule => ({
  id: 'r1',
  joint: 'elbow_flexion',
  side: 'signal',
  phases: ['moving'],
  min_deg: min,
  max_deg: max,
  sustain_ms: 400,
  message: 'x',
  blocks_rep: false,
  out_of_plane_limit: 0.6,
})

describe('feedback helpers', () => {
  it('logs each message once, newest first, bounded', () => {
    let log: FeedbackMessage[] = []
    log = appendToLog(log, msg(1))
    log = appendToLog(log, msg(1))
    log = appendToLog(log, null)
    log = appendToLog(log, msg(2))
    expect(log.map((m) => m.seq)).toEqual([2, 1])
    for (let i = 3; i < 20; i++) log = appendToLog(log, msg(i), 5)
    expect(log).toHaveLength(5)
    expect(log[0]?.seq).toBe(19)
  })

  it('describes rule bounds', () => {
    expect(describeRuleBounds(rule(null, 40))).toBe('≤ 40°')
    expect(describeRuleBounds(rule(20, null))).toBe('≥ 20°')
    expect(describeRuleBounds(rule(20, 60))).toBe('20°–60°')
  })
})
