import { describe, expect, it } from 'vitest'

import type { AngleDefinition, AngleMeasurement } from '../types/protocol'
import { angleStatusText, formatAngle, groupAngles } from './angles'

const def = (side: 'left' | 'right', joint: string, label: string): AngleDefinition => ({
  id: `${side}_${joint}`,
  label: `${side === 'left' ? 'Left' : 'Right'} ${label}`,
  joint,
  side,
  landmarks: [0, 1, 2],
  convention: 'flexion',
  description: '',
})

const m = (id: string, status: AngleMeasurement['status'], value: number | null): AngleMeasurement => ({
  id,
  status,
  value_deg: value,
  raw_deg: value,
  confidence: 0.9,
})

describe('angles', () => {
  it('groups left/right definitions into one row per joint', () => {
    const defs = [def('left', 'elbow_flexion', 'elbow flexion'), def('right', 'elbow_flexion', 'elbow flexion')]
    const rows = groupAngles(defs, [m('left_elbow_flexion', 'ok', 88.6)])
    expect(rows).toHaveLength(1)
    expect(rows[0]?.label).toBe('elbow flexion')
    expect(rows[0]?.left?.measurement?.value_deg).toBe(88.6)
    expect(rows[0]?.right?.measurement).toBeNull()
  })

  it('formats only valid measurements as numbers', () => {
    expect(formatAngle(m('x', 'ok', 88.6))).toBe('89°')
    expect(formatAngle(m('x', 'low_visibility', null))).toBeNull()
    expect(formatAngle(null)).toBeNull()
    expect(angleStatusText(m('x', 'out_of_frame', null))).toBe('out of frame')
  })
})
