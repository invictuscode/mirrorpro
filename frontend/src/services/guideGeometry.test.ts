import { describe, expect, it } from 'vitest'

import { computeGuide, guideMode, wrap } from './guideGeometry'

const close = (a: number, b: number) => expect(a).toBeCloseTo(b, 3)

describe('guide geometry', () => {
  // Elbow: shoulder above the elbow, forearm hanging straight down (flexion 0°).
  const a = { x: 100, y: 0 }
  const b = { x: 100, y: 100 }
  const straight = { x: 100, y: 200 }

  it('places the target ghost at the target flexion on the side the arm bends', () => {
    // Forearm slightly forward (+x) so the bend side is known.
    const c = { x: 110, y: 199 }
    const g = computeGuide({ a, b, c, convention: 'flexion', startDeg: 0, targetDeg: 90, mode: 'to_target' })
    expect(g).not.toBeNull()
    // 90° flexion: forearm horizontal, on the +x side, same length (~100).
    close(g!.ghostTarget.y, 100)
    expect(g!.ghostTarget.x).toBeGreaterThan(190)
    // Start ghost (0°): straight down.
    close(g!.ghostStart.x, 100)
    expect(g!.ghostStart.y).toBeGreaterThan(195)
  })

  it('arrow rotates toward the target, capped at 50°', () => {
    const g = computeGuide({ a, b, c: straight, convention: 'flexion', startDeg: 0, targetDeg: 120, mode: 'to_target' })!
    const sweep = g.arrow!.to - g.arrow!.from
    close(Math.abs(sweep), (50 * Math.PI) / 180)
  })

  it('arrow points back toward the start when returning, and is absent when already there', () => {
    const bent = { x: 200, y: 100 } // 90° flexion
    const toStart = computeGuide({ a, b, c: bent, convention: 'flexion', startDeg: 0, targetDeg: 90, mode: 'to_start' })!
    const toTarget = computeGuide({ a, b, c: bent, convention: 'flexion', startDeg: 0, targetDeg: 90, mode: 'to_target' })!
    expect(toTarget.arrow).toBeNull() // already at the target
    expect(toStart.arrow).not.toBeNull()
    expect(computeGuide({ a, b, c: bent, convention: 'flexion', startDeg: 0, targetDeg: 90, mode: 'hold' })!.arrow).toBeNull()
  })

  it('handles the included-angle convention (shoulder elevation)', () => {
    // Hip below the shoulder, arm hanging (elevation 0°); target 90° = arm horizontal.
    const hip = { x: 100, y: 300 }
    const shoulder = { x: 100, y: 100 }
    const elbow = { x: 105, y: 200 }
    const g = computeGuide({ a: hip, b: shoulder, c: elbow, convention: 'included', startDeg: 0, targetDeg: 90, mode: 'to_target' })!
    close(g.ghostTarget.y, 100)
    expect(g.ghostTarget.x).toBeGreaterThan(195)
  })

  it('rejects degenerate input', () => {
    expect(computeGuide({ a: b, b, c: straight, convention: 'flexion', startDeg: 0, targetDeg: 90, mode: 'to_target' })).toBeNull()
  })

  it('maps phases to guide modes', () => {
    expect(guideMode('ready', 0, 0)).toBe('to_target')
    expect(guideMode('at_target', 200, 1000)).toBe('hold')
    expect(guideMode('at_target', 1200, 1000)).toBe('to_start')
    expect(guideMode('returning', 0, 0)).toBe('to_start')
    close(wrap(3 * Math.PI), Math.PI)
  })
})
