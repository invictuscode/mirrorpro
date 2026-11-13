import { computeGuide, type GuideMode, type Pt } from '../services/guideGeometry'
import type { Landmark, RuleState } from '../types/protocol'

/** One limb to guide (a joint-angle definition on one side). */
export interface GuideSpec {
  landmarks: [number, number, number] // proximal, vertex, distal
  convention: 'flexion' | 'included'
  startDeg: number
  targetDeg: number
  mode: GuideMode
}

/** A joint that must stay steady, coloured by its rule's live state. */
export interface Highlight {
  landmark: number
  state: RuleState
}

const C = {
  target: '#3ddc84',
  start: 'rgba(232, 237, 242, 0.55)',
  arrow: '#8fb4ff',
  outline: 'rgba(7, 9, 11, 0.85)',
  ok: '#4fd1c5',
  violated: '#f2645a',
  uncertain: 'rgba(232, 237, 242, 0.5)',
}

const px = (lm: Landmark, w: number, h: number): Pt => ({ x: lm[0] * w, y: lm[1] * h })

export function drawGuides(
  ctx: CanvasRenderingContext2D,
  lms: Landmark[],
  guides: GuideSpec[],
  w: number,
  h: number,
  scale: number,
  mirrored: boolean,
): void {
  for (const g of guides) {
    const [ia, ib, ic] = g.landmarks
    const la = lms[ia]
    const lb = lms[ib]
    const lc = lms[ic]
    if (!la || !lb || !lc) continue
    const geo = computeGuide({
      a: px(la, w, h),
      b: px(lb, w, h),
      c: px(lc, w, h),
      convention: g.convention,
      startDeg: g.startDeg,
      targetDeg: g.targetDeg,
      mode: g.mode,
    })
    if (!geo) continue
    // Start position (dimmer, dashed) and target position (bright).
    segment(ctx, geo.vertex, geo.ghostStart, C.start, 4 * scale, [8 * scale, 8 * scale])
    segment(ctx, geo.vertex, geo.ghostTarget, C.target, 6 * scale, [])
    label(ctx, geo.ghostTarget, 'target', C.target, scale, mirrored)
    if (geo.arrow) {
      arcArrow(ctx, geo.vertex, geo.arrow.radius, geo.arrow.from, geo.arrow.to, scale)
    } else if (g.mode === 'hold') {
      ring(ctx, geo.vertex, 22 * scale, C.target, 4 * scale, [])
      label(ctx, { x: geo.vertex.x, y: geo.vertex.y - 30 * scale }, 'hold', C.target, scale, mirrored)
    }
  }
}

export function drawHighlights(
  ctx: CanvasRenderingContext2D,
  lms: Landmark[],
  highlights: Highlight[],
  w: number,
  h: number,
  scale: number,
): void {
  for (const hl of highlights) {
    const lm = lms[hl.landmark]
    if (!lm || hl.state === 'inactive') continue
    const p = px(lm, w, h)
    if (hl.state === 'violated') ring(ctx, p, 16 * scale, C.violated, 5 * scale, [])
    else if (hl.state === 'uncertain') ring(ctx, p, 14 * scale, C.uncertain, 3 * scale, [5 * scale, 5 * scale])
    else ring(ctx, p, 13 * scale, C.ok, 3 * scale, [])
  }
}

function segment(ctx: CanvasRenderingContext2D, a: Pt, b: Pt, color: string, width: number, dash: number[]): void {
  ctx.save()
  ctx.lineCap = 'round'
  ctx.setLineDash(dash)
  // Dark outline first so the guide stays visible over any video background.
  ctx.strokeStyle = C.outline
  ctx.lineWidth = width + 4
  ctx.beginPath()
  ctx.moveTo(a.x, a.y)
  ctx.lineTo(b.x, b.y)
  ctx.stroke()
  ctx.strokeStyle = color
  ctx.lineWidth = width
  ctx.stroke()
  ctx.restore()
}

function ring(ctx: CanvasRenderingContext2D, p: Pt, r: number, color: string, width: number, dash: number[]): void {
  ctx.save()
  ctx.setLineDash(dash)
  ctx.strokeStyle = color
  ctx.lineWidth = width
  ctx.beginPath()
  ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
  ctx.stroke()
  ctx.restore()
}

function arcArrow(ctx: CanvasRenderingContext2D, c: Pt, r: number, from: number, to: number, scale: number): void {
  const ccw = to < from
  ctx.save()
  ctx.lineCap = 'round'
  for (const [color, width] of [
    [C.outline, 10 * scale],
    [C.arrow, 6 * scale],
  ] as const) {
    ctx.strokeStyle = color
    ctx.lineWidth = width
    ctx.beginPath()
    ctx.arc(c.x, c.y, r, from, to, ccw)
    ctx.stroke()
  }
  // Arrowhead tangent to the arc at its end.
  const tip = { x: c.x + r * Math.cos(to), y: c.y + r * Math.sin(to) }
  const dir = to + (ccw ? -Math.PI / 2 : Math.PI / 2)
  const size = 16 * scale
  ctx.fillStyle = C.arrow
  ctx.strokeStyle = C.outline
  ctx.lineWidth = 2 * scale
  ctx.beginPath()
  ctx.moveTo(tip.x + size * Math.cos(dir), tip.y + size * Math.sin(dir))
  ctx.lineTo(tip.x + size * 0.6 * Math.cos(dir + 2.3), tip.y + size * 0.6 * Math.sin(dir + 2.3))
  ctx.lineTo(tip.x + size * 0.6 * Math.cos(dir - 2.3), tip.y + size * 0.6 * Math.sin(dir - 2.3))
  ctx.closePath()
  ctx.stroke()
  ctx.fill()
  ctx.restore()
}

/** Text that stays readable when the canvas is CSS-mirrored. */
function label(ctx: CanvasRenderingContext2D, p: Pt, text: string, color: string, scale: number, mirrored: boolean): void {
  ctx.save()
  ctx.translate(p.x, p.y - 14 * scale)
  if (mirrored) ctx.scale(-1, 1)
  ctx.font = `700 ${Math.round(15 * scale)}px ui-sans-serif, -apple-system, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'
  ctx.lineWidth = 4 * scale
  ctx.strokeStyle = C.outline
  ctx.strokeText(text, 0, 0)
  ctx.fillStyle = color
  ctx.fillText(text, 0, 0)
  ctx.restore()
}
