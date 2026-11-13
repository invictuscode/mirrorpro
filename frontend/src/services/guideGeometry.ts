/**
 * Geometry for the on-camera exercise guides: where the moving segment should
 * end up ("ghost" lines at the start and target angles) and which way to
 * rotate (an arc arrow around the joint). Works in canvas pixel coordinates,
 * i.e. the same aspect-corrected 2D space the angles are measured in.
 *
 * For a joint angle ABC (proximal A, vertex B, distal C), the included angle
 * θ relates to the displayed value by the definition's convention: flexion
 * value = 180° − θ, included value = θ.
 */

export interface Pt {
  x: number
  y: number
}

export type GuideMode = 'to_target' | 'to_start' | 'hold'

export interface GuideInput {
  a: Pt
  b: Pt
  c: Pt
  convention: 'flexion' | 'included'
  startDeg: number
  targetDeg: number
  mode: GuideMode
}

export interface GuideGeometry {
  vertex: Pt
  ghostTarget: Pt // end of the distal segment at the target angle
  ghostStart: Pt
  arrow: { radius: number; from: number; to: number } | null // radians around the vertex
}

const RAD = Math.PI / 180
const MAX_SWEEP = 50 * RAD
const MIN_SWEEP = 6 * RAD

export function includedFor(convention: 'flexion' | 'included', valueDeg: number): number {
  return (convention === 'flexion' ? 180 - valueDeg : valueDeg) * RAD
}

/** Wrap to (−π, π]. */
export function wrap(a: number): number {
  let x = a
  while (x <= -Math.PI) x += 2 * Math.PI
  while (x > Math.PI) x -= 2 * Math.PI
  return x
}

export function computeGuide(g: GuideInput): GuideGeometry | null {
  const ba = { x: g.a.x - g.b.x, y: g.a.y - g.b.y }
  const bc = { x: g.c.x - g.b.x, y: g.c.y - g.b.y }
  const len = Math.hypot(bc.x, bc.y)
  if (len < 1 || Math.hypot(ba.x, ba.y) < 1) return null
  // Side of the proximal segment the distal segment is on: keeps the ghost
  // limb on the same side the person is actually moving.
  const cross = bc.x * ba.y - bc.y * ba.x
  const s = cross >= 0 ? 1 : -1
  const angA = Math.atan2(ba.y, ba.x)
  const angC = Math.atan2(bc.y, bc.x)
  const at = (valueDeg: number): Pt => {
    const ang = angA - s * includedFor(g.convention, valueDeg)
    return { x: g.b.x + len * Math.cos(ang), y: g.b.y + len * Math.sin(ang) }
  }
  const ghostTarget = at(g.targetDeg)
  const ghostStart = at(g.startDeg)

  let arrow: GuideGeometry['arrow'] = null
  if (g.mode !== 'hold') {
    const dest = g.mode === 'to_target' ? ghostTarget : ghostStart
    const delta = wrap(Math.atan2(dest.y - g.b.y, dest.x - g.b.x) - angC)
    if (Math.abs(delta) >= MIN_SWEEP) {
      const sweep = Math.sign(delta) * Math.min(Math.abs(delta), MAX_SWEEP)
      arrow = { radius: 0.6 * len, from: angC, to: angC + sweep }
    }
  }
  return { vertex: g.b, ghostTarget, ghostStart, arrow }
}

/** Which way to guide for the current repetition phase. */
export function guideMode(
  phase: 'waiting_for_start' | 'ready' | 'moving' | 'at_target' | 'returning',
  holdMs: number,
  minHoldMs: number,
): GuideMode {
  switch (phase) {
    case 'waiting_for_start':
    case 'returning':
      return 'to_start'
    case 'ready':
    case 'moving':
      return 'to_target'
    case 'at_target':
      return holdMs < minHoldMs ? 'hold' : 'to_start'
  }
}
