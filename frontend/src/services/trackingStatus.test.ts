import { describe, expect, it } from 'vitest'

import { PROTOCOL_VERSION, type FrameMessage, type Landmark, type StatusMessage } from '../types/protocol'
import { describeTrackingStatus } from './trackingStatus'

const status = (state: StatusMessage['state'], error: StatusMessage['error'] = null): StatusMessage => ({
  type: 'status',
  protocol_version: PROTOCOL_VERSION,
  state,
  error,
  camera: null,
  model: 'm.task',
  profile: 'dev',
  preview_enabled: true,
  angle_space: 'world',
})

const frame = (visibility: number | null): FrameMessage => ({
  type: 'frame',
  frame_id: 1,
  timestamp_ms: 0,
  width: 640,
  height: 480,
  person_detected: visibility !== null,
  landmarks: visibility === null ? null : Array.from({ length: 33 }, (): Landmark => [0.5, 0.5, 0, visibility, visibility]),
  has_preview: true,
  angle_space: 'image',
  exercise: null,
  angles: [],
  metrics: { capture_fps: 30, inference_fps: 30, inference_ms: 10, latency_ms: 10, dropped_frames: 0 },
})

describe('describeTrackingStatus', () => {
  it('reports backend connection problems first', () => {
    expect(describeTrackingStatus('closed', null, null, null)).toMatchObject({ severity: 'error', blocking: true })
    expect(describeTrackingStatus('connecting', null, null, null).severity).toBe('info')
  })

  it('surfaces pipeline errors with their message', () => {
    const s = describeTrackingStatus(
      'open',
      status('error', { code: 'camera_open_failed', message: 'denied' }),
      null,
      null,
    )
    expect(s).toMatchObject({ severity: 'error', title: 'Camera unavailable', detail: 'denied' })
  })

  it('distinguishes no person, uncertain tracking, and good tracking', () => {
    expect(describeTrackingStatus('open', status('running'), frame(null), 10).title).toBe('No person detected')
    expect(describeTrackingStatus('open', status('running'), frame(0.2), 10).title).toBe('Tracking uncertain')
    expect(describeTrackingStatus('open', status('running'), frame(0.95), 10).severity).toBe('ok')
  })

  it('blocks on a protocol version mismatch', () => {
    const old = { ...status('running'), protocol_version: PROTOCOL_VERSION - 1 }
    expect(describeTrackingStatus('open', old, frame(0.95), 10)).toMatchObject({ severity: 'error', blocking: true })
  })

  it('flags stale frames even if the last one had a person', () => {
    expect(describeTrackingStatus('open', status('running'), frame(0.95), 5000).title).toBe('No new frames')
  })
})
