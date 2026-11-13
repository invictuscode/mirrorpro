import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

import { PoseStreamClient, streamUrl, type ConnectionState, type DecodedFrame } from '../services/streamClient'
import type { FrameMessage, SessionView, StatusMessage } from '../types/protocol'

/** Sliding-window events-per-second counter. */
export class RateCounter {
  private times: number[] = []
  private readonly windowMs: number
  constructor(windowMs = 1000) {
    this.windowMs = windowMs
  }
  tick(now = performance.now()): void {
    this.times.push(now)
    this.trim(now)
  }
  rate(now = performance.now()): number {
    this.trim(now)
    const first = this.times[0]
    const last = this.times[this.times.length - 1]
    if (this.times.length < 2 || first === undefined || last === undefined || last === first) return 0
    return ((this.times.length - 1) * 1000) / (last - first)
  }
  private trim(now: number): void {
    while (this.times.length && now - (this.times[0] ?? now) > this.windowMs) this.times.shift()
  }
}

export interface StreamSnapshot {
  message: FrameMessage | null
  /** Milliseconds since the last frame arrived, or null if none yet. */
  frameAgeMs: number | null
  receivedFps: number
}

export interface PoseStream {
  connection: ConnectionState
  status: StatusMessage | null
  /** Updated per frame without re-rendering React; read it in a rAF loop. */
  frameRef: RefObject<DecodedFrame | null>
  /** Throttled copy of the latest frame metadata for text panels. */
  snapshot: StreamSnapshot
  protocolError: string | null
  /** Latest session pushed by the backend, with the local time it arrived
   * (used to extrapolate timers between messages). */
  session: TimedSession | null
  /** Apply a status returned by a REST call before the WebSocket echoes it. */
  applyStatus: (status: StatusMessage) => void
  /** Same for a session view returned by a REST call. */
  applySession: (view: SessionView | null) => void
}

export interface TimedSession {
  view: SessionView
  receivedAt: number
}

const SNAPSHOT_INTERVAL_MS = 250

export function usePoseStream(): PoseStream {
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [status, setStatus] = useState<StatusMessage | null>(null)
  const [protocolError, setProtocolError] = useState<string | null>(null)
  const [session, setSession] = useState<TimedSession | null>(null)
  const [snapshot, setSnapshot] = useState<StreamSnapshot>({ message: null, frameAgeMs: null, receivedFps: 0 })
  const frameRef = useRef<DecodedFrame | null>(null)
  const received = useRef(new RateCounter())

  useEffect(() => {
    const client = new PoseStreamClient(streamUrl(), {
      onConnection: (state) => {
        setConnection(state)
        if (state !== 'open') setStatus(null)
      },
      onStatus: (s) => {
        setStatus(s)
        if (s.state !== 'running') {
          frameRef.current?.image?.close()
          frameRef.current = null
        }
      },
      onSession: (view) => setSession(view ? { view, receivedAt: performance.now() } : null),
      onFrame: (frame) => {
        const previous = frameRef.current
        frameRef.current = frame
        previous?.image?.close()
        received.current.tick()
        setProtocolError(null)
      },
      onProtocolError: (err) => {
        console.error('Stream protocol error', err)
        setProtocolError(err.message)
      },
    })
    client.connect()

    const timer = window.setInterval(() => {
      const frame = frameRef.current
      setSnapshot({
        message: frame?.message ?? null,
        frameAgeMs: frame ? performance.now() - frame.receivedAt : null,
        receivedFps: received.current.rate(),
      })
    }, SNAPSHOT_INTERVAL_MS)

    return () => {
      window.clearInterval(timer)
      client.close()
      frameRef.current?.image?.close()
      frameRef.current = null
    }
  }, [])

  const applySession = useCallback(
    (view: SessionView | null) => setSession(view ? { view, receivedAt: performance.now() } : null),
    [],
  )

  return { connection, status, frameRef, snapshot, protocolError, session, applyStatus: setStatus, applySession }
}
