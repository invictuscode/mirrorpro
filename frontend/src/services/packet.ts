import type { FrameMessage, SessionMessage, StatusMessage } from '../types/protocol'

/**
 * Binary frame packet: [uint32 BE N][N bytes UTF-8 JSON FrameMessage][JPEG bytes?]
 */
export interface FramePacket {
  message: FrameMessage
  jpeg: Uint8Array | null
}

export class PacketError extends Error {}

const decoder = new TextDecoder()

export function parseFramePacket(buffer: ArrayBuffer): FramePacket {
  if (buffer.byteLength < 4) throw new PacketError('Packet shorter than header')
  const jsonLength = new DataView(buffer).getUint32(0, false)
  const end = 4 + jsonLength
  if (end > buffer.byteLength) throw new PacketError('Header length exceeds packet size')

  const parsed: unknown = JSON.parse(decoder.decode(new Uint8Array(buffer, 4, jsonLength)))
  if (!isFrameMessage(parsed)) throw new PacketError('Packet JSON is not a frame message')
  const jpeg = end < buffer.byteLength ? new Uint8Array(buffer, end) : null
  return { message: parsed, jpeg }
}

export type TextMessage = StatusMessage | SessionMessage

/** Text WebSocket messages: pipeline `status` or exercise `session`. */
export function parseTextMessage(text: string): TextMessage {
  const parsed: unknown = JSON.parse(text)
  if (typeof parsed !== 'object' || parsed === null) throw new PacketError('Text message is not an object')
  const v = parsed as { type?: unknown; state?: unknown; session?: unknown }
  if (v.type === 'status' && typeof v.state === 'string') return parsed as StatusMessage
  if (v.type === 'session' && (v.session === null || typeof v.session === 'object')) return parsed as SessionMessage
  throw new PacketError(`Unknown text message type ${JSON.stringify(v.type)}`)
}

function isFrameMessage(value: unknown): value is FrameMessage {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Partial<FrameMessage>
  return (
    v.type === 'frame' &&
    typeof v.frame_id === 'number' &&
    typeof v.width === 'number' &&
    typeof v.height === 'number' &&
    typeof v.person_detected === 'boolean' &&
    (v.landmarks === null || Array.isArray(v.landmarks)) &&
    Array.isArray(v.angles) &&
    typeof v.metrics === 'object'
  )
}
