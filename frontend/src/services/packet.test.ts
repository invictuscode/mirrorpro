import { describe, expect, it } from 'vitest'

import type { FrameMessage } from '../types/protocol'
import { PacketError, parseFramePacket, parseTextMessage } from './packet'

const message: FrameMessage = {
  type: 'frame',
  frame_id: 3,
  timestamp_ms: 1000,
  width: 640,
  height: 480,
  person_detected: true,
  landmarks: [[0.5, 0.5, 0, 0.9, 0.9]],
  has_preview: true,
  angle_space: 'image',
  exercise: null,
  angles: [{ id: 'left_elbow_flexion', status: 'ok', value_deg: 42.5, raw_deg: 43, confidence: 0.9 }],
  metrics: { capture_fps: 30, inference_fps: 30, inference_ms: 10, latency_ms: 15, dropped_frames: 0 },
}

function encode(json: unknown, tail: number[] = []): ArrayBuffer {
  const body = new TextEncoder().encode(JSON.stringify(json))
  const out = new Uint8Array(4 + body.length + tail.length)
  new DataView(out.buffer).setUint32(0, body.length, false)
  out.set(body, 4)
  out.set(tail, 4 + body.length)
  return out.buffer
}

describe('parseFramePacket', () => {
  it('splits JSON and JPEG payload', () => {
    const { message: m, jpeg } = parseFramePacket(encode(message, [0xff, 0xd8, 0xff, 0xd9]))
    expect(m).toEqual(message)
    expect(Array.from(jpeg ?? [])).toEqual([0xff, 0xd8, 0xff, 0xd9])
  })

  it('returns null jpeg when no preview is attached', () => {
    expect(parseFramePacket(encode({ ...message, has_preview: false })).jpeg).toBeNull()
  })

  it('rejects truncated or malformed packets', () => {
    expect(() => parseFramePacket(new ArrayBuffer(2))).toThrow(PacketError)
    const bad = new Uint8Array(8)
    new DataView(bad.buffer).setUint32(0, 100, false)
    expect(() => parseFramePacket(bad.buffer)).toThrow(PacketError)
    expect(() => parseFramePacket(encode({ type: 'status' }))).toThrow(PacketError)
  })
})

describe('parseTextMessage', () => {
  it('accepts status and session messages and rejects others', () => {
    expect(parseTextMessage('{"type":"status","state":"running"}')).toMatchObject({ type: 'status', state: 'running' })
    expect(parseTextMessage('{"type":"session","session":null}')).toEqual({ type: 'session', session: null })
    expect(() => parseTextMessage('{"type":"frame"}')).toThrow(PacketError)
    expect(() => parseTextMessage('[]')).toThrow(PacketError)
  })
})
