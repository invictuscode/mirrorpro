import type { FrameMessage, SessionView, StatusMessage } from '../types/protocol'
import { parseFramePacket, parseTextMessage } from './packet'

export type ConnectionState = 'connecting' | 'open' | 'closed'

/** A frame ready to draw. `image` is null when the backend sends no preview. */
export interface DecodedFrame {
  message: FrameMessage
  image: ImageBitmap | null
  receivedAt: number
}

export interface StreamHandlers {
  onConnection: (state: ConnectionState) => void
  onStatus: (status: StatusMessage) => void
  onSession: (session: SessionView | null) => void
  onFrame: (frame: DecodedFrame) => void
  onProtocolError: (error: Error) => void
}

const MIN_RETRY_MS = 500
const MAX_RETRY_MS = 5000

/**
 * WebSocket client for /ws/stream with automatic reconnect.
 *
 * JPEG decoding uses createImageBitmap (off the main thread in modern
 * browsers). At most one decode is in flight; if packets arrive faster than
 * they decode, only the newest pending packet is kept, so the UI never falls
 * behind real time.
 */
export class PoseStreamClient {
  private ws: WebSocket | null = null
  private retryMs = MIN_RETRY_MS
  private retryTimer: number | undefined
  private closed = false
  private decoding = false
  private pending: ArrayBuffer | null = null
  private readonly url: string
  private readonly handlers: StreamHandlers

  constructor(url: string, handlers: StreamHandlers) {
    this.url = url
    this.handlers = handlers
  }

  connect(): void {
    this.closed = false
    this.handlers.onConnection('connecting')
    const ws = new WebSocket(this.url)
    ws.binaryType = 'arraybuffer'
    this.ws = ws

    ws.onopen = () => {
      this.retryMs = MIN_RETRY_MS
      this.handlers.onConnection('open')
    }
    ws.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
      try {
        if (typeof event.data === 'string') {
          const msg = parseTextMessage(event.data)
          if (msg.type === 'status') this.handlers.onStatus(msg)
          else this.handlers.onSession(msg.session)
        } else {
          this.enqueue(event.data)
        }
      } catch (err) {
        this.handlers.onProtocolError(err instanceof Error ? err : new Error(String(err)))
      }
    }
    ws.onclose = () => {
      this.ws = null
      this.handlers.onConnection('closed')
      if (!this.closed) {
        this.retryTimer = window.setTimeout(() => this.connect(), this.retryMs)
        this.retryMs = Math.min(this.retryMs * 2, MAX_RETRY_MS)
      }
    }
    // onerror is always followed by onclose, which handles reconnecting.
  }

  close(): void {
    this.closed = true
    window.clearTimeout(this.retryTimer)
    this.ws?.close()
    this.ws = null
    this.pending = null
  }

  private enqueue(buffer: ArrayBuffer): void {
    if (this.decoding) {
      this.pending = buffer // drop any older pending packet
      return
    }
    void this.decode(buffer)
  }

  private async decode(buffer: ArrayBuffer): Promise<void> {
    this.decoding = true
    try {
      const { message, jpeg } = parseFramePacket(buffer)
      let image: ImageBitmap | null = null
      if (jpeg) {
        // Copy into a fresh ArrayBuffer-backed view: Blob requires that.
        image = await createImageBitmap(new Blob([new Uint8Array(jpeg)], { type: 'image/jpeg' }))
      }
      if (this.closed) image?.close()
      else this.handlers.onFrame({ message, image, receivedAt: performance.now() })
    } catch (err) {
      this.handlers.onProtocolError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      this.decoding = false
      const next = this.pending
      this.pending = null
      if (next && !this.closed) void this.decode(next)
    }
  }
}

export function streamUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/stream`
}
