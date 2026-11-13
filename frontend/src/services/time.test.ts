import { describe, expect, it } from 'vitest'

import type { SessionView } from '../types/protocol'
import { countdownSeconds, formatDuration, liveTimers } from './time'

const view = (state: SessionView['state'], active: number, rest: number | null): SessionView =>
  ({ state, active_ms: active, rest_remaining_ms: rest }) as SessionView

describe('time helpers', () => {
  it('formats durations', () => {
    expect(formatDuration(0)).toBe('0:00')
    expect(formatDuration(65_400)).toBe('1:05')
    expect(formatDuration(3_725_000)).toBe('1:02:05')
    expect(formatDuration(-5)).toBe('0:00')
  })

  it('rounds countdowns up', () => {
    expect(countdownSeconds(29_001)).toBe(30)
    expect(countdownSeconds(0)).toBe(0)
  })

  it('extrapolates only the running timer', () => {
    expect(liveTimers(view('active', 10_000, null), 1000, 3000)).toEqual({ activeMs: 12_000, restRemainingMs: null })
    expect(liveTimers(view('resting', 10_000, 30_000), 1000, 6000)).toEqual({ activeMs: 10_000, restRemainingMs: 25_000 })
    expect(liveTimers(view('paused', 10_000, 30_000), 1000, 60_000)).toEqual({ activeMs: 10_000, restRemainingMs: 30_000 })
    expect(liveTimers(view('resting', 0, 2000), 0, 9000).restRemainingMs).toBe(0)
  })
})
