import { useEffect, useRef, type RefObject } from 'react'

import { drawGuides, drawHighlights, type GuideSpec, type Highlight } from './guideOverlay'
import type { DecodedFrame } from '../services/streamClient'
import { formatAngle } from '../services/angles'
import { LM_VISIBILITY, type AngleDefinition, type Landmark, type Topology } from '../types/protocol'

/** Visibility bands used for colouring. MediaPipe's visibility is a model
 * score, not a calibrated probability, so these bands are qualitative. */
export const VIS_HIGH = 0.75
export const VIS_MEDIUM = 0.5

const COLORS = {
  high: '#4fd1c5',
  medium: '#f5b544',
  low: 'rgba(242, 100, 90, 0.75)',
  bone: 'rgba(232, 237, 242, 0.85)',
  boneUncertain: 'rgba(232, 237, 242, 0.25)',
  background: '#07090b',
}

export function visibilityColor(v: number): string {
  if (v >= VIS_HIGH) return COLORS.high
  if (v >= VIS_MEDIUM) return COLORS.medium
  return COLORS.low
}

interface Props {
  frameRef: RefObject<DecodedFrame | null>
  topology: Topology | null
  mirrored: boolean
  showVideo: boolean
  angleDefinitions: AngleDefinition[]
  showAngles: boolean
  /** Movement guides (ghost limbs + direction arrow), e.g. for the practice rep. */
  guides?: GuideSpec[]
  /** Joints that must stay steady, coloured by their rule's live state. */
  highlights?: Highlight[]
  onDraw?: () => void
}

interface DrawOptions {
  topology: Topology | null
  showVideo: boolean
  angleDefinitions: AngleDefinition[]
  showAngles: boolean
  mirrored: boolean
  guides: GuideSpec[]
  highlights: Highlight[]
}

const NONE: never[] = []

/**
 * Draws the latest frame and skeleton in a requestAnimationFrame loop. Redraws
 * only when a new frame arrives, independent of React renders.
 */
export function PoseCanvas({
  frameRef,
  topology,
  mirrored,
  showVideo,
  angleDefinitions,
  showAngles,
  guides = NONE,
  highlights = NONE,
  onDraw,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  // Keep latest props visible to the rAF loop without restarting it.
  const opts = useRef<DrawOptions>({ topology, showVideo, angleDefinitions, showAngles, mirrored, guides, highlights })
  opts.current = { topology, showVideo, angleDefinitions, showAngles, mirrored, guides, highlights }
  const drawCallback = useRef(onDraw)
  drawCallback.current = onDraw

  useEffect(() => {
    let raf = 0
    let lastFrame: DecodedFrame | null = null
    let lastOpts: DrawOptions | null = null

    const loop = () => {
      raf = requestAnimationFrame(loop)
      const canvas = canvasRef.current
      const frame = frameRef.current
      const o = opts.current
      const isNewFrame = frame !== lastFrame
      // Redraw on a new frame, or when display options change (e.g. mirroring).
      if (!canvas || (!isNewFrame && o === lastOpts)) return
      lastFrame = frame
      lastOpts = o
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      if (!frame) {
        ctx.clearRect(0, 0, canvas.width, canvas.height)
        return
      }
      draw(ctx, canvas, frame, o)
      if (isNewFrame) drawCallback.current?.()
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [frameRef])

  return (
    <canvas
      ref={canvasRef}
      className="pose-canvas"
      style={{ transform: mirrored ? 'scaleX(-1)' : undefined }}
      aria-label="Camera view with detected body landmarks"
      role="img"
    />
  )
}

function draw(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, frame: DecodedFrame, o: DrawOptions): void {
  const { message, image } = frame
  // Canvas resolution follows the preview image, or the source aspect ratio
  // when there is no preview.
  const w = image?.width ?? 960
  const h = image?.height ?? Math.round((960 * message.height) / message.width)
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w
    canvas.height = h
  }

  if (image && o.showVideo) {
    ctx.drawImage(image, 0, 0, w, h)
  } else {
    ctx.fillStyle = COLORS.background
    ctx.fillRect(0, 0, w, h)
  }

  const lms = message.landmarks
  if (!lms) return
  const scale = w / 640
  drawBones(ctx, lms, o.topology, w, h, scale)
  drawJoints(ctx, lms, w, h, scale)
  if (o.highlights.length) drawHighlights(ctx, lms, o.highlights, w, h, scale)
  if (o.guides.length) drawGuides(ctx, lms, o.guides, w, h, scale, o.mirrored)
  if (o.showAngles) drawAngleLabels(ctx, frame, o.angleDefinitions, o.mirrored, w, h, scale)
}

/** Draws each valid angle next to its joint. The canvas is CSS-flipped in
 * mirror view, so text is counter-flipped to stay readable, and anchored on
 * the side of the joint away from the body's midline. */
function drawAngleLabels(
  ctx: CanvasRenderingContext2D,
  frame: DecodedFrame,
  definitions: AngleDefinition[],
  mirrored: boolean,
  w: number,
  h: number,
  scale: number,
): void {
  const lms = frame.message.landmarks
  if (!lms) return
  const byId = new Map(definitions.map((d) => [d.id, d]))
  const hips = [lms[23], lms[24]].filter((p): p is Landmark => p !== undefined)
  const midX = hips.length ? (hips.reduce((s, p) => s + p[0], 0) / hips.length) * w : w / 2

  ctx.font = `600 ${Math.round(15 * scale)}px ui-sans-serif, -apple-system, sans-serif`
  ctx.textBaseline = 'middle'
  for (const m of frame.message.angles) {
    const text = formatAngle(m)
    const vertex = byId.get(m.id)?.landmarks[1]
    const p = vertex === undefined ? undefined : lms[vertex]
    if (!text || !p) continue
    const x = p[0] * w
    const y = p[1] * h
    const dir = x >= midX ? 1 : -1
    const screenDir = mirrored ? -dir : dir
    const pad = 4 * scale
    const tw = ctx.measureText(text).width

    ctx.save()
    ctx.translate(x + dir * 14 * scale, y)
    if (mirrored) ctx.scale(-1, 1)
    const left = screenDir > 0 ? 0 : -tw
    ctx.fillStyle = 'rgba(7, 9, 11, 0.72)'
    ctx.fillRect(left - pad, -10 * scale, tw + pad * 2, 20 * scale)
    ctx.fillStyle = '#e8edf2'
    ctx.textAlign = 'left'
    ctx.fillText(text, left, 0)
    ctx.restore()
  }
}

function drawBones(
  ctx: CanvasRenderingContext2D,
  lms: Landmark[],
  topology: Topology | null,
  w: number,
  h: number,
  scale: number,
): void {
  if (!topology) return
  ctx.lineCap = 'round'
  for (const [a, b] of topology.connections) {
    const p = lms[a]
    const q = lms[b]
    if (!p || !q) continue
    const certain = Math.min(p[LM_VISIBILITY], q[LM_VISIBILITY]) >= VIS_MEDIUM
    ctx.strokeStyle = certain ? COLORS.bone : COLORS.boneUncertain
    ctx.lineWidth = (certain ? 3 : 2) * scale
    ctx.setLineDash(certain ? [] : [6 * scale, 6 * scale])
    ctx.beginPath()
    ctx.moveTo(p[0] * w, p[1] * h)
    ctx.lineTo(q[0] * w, q[1] * h)
    ctx.stroke()
  }
  ctx.setLineDash([])
}

function drawJoints(ctx: CanvasRenderingContext2D, lms: Landmark[], w: number, h: number, scale: number): void {
  for (const lm of lms) {
    const v = lm[LM_VISIBILITY]
    ctx.fillStyle = visibilityColor(v)
    ctx.beginPath()
    ctx.arc(lm[0] * w, lm[1] * h, (v >= VIS_MEDIUM ? 5 : 3.5) * scale, 0, Math.PI * 2)
    ctx.fill()
  }
}
