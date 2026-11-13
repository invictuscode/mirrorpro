import type { AngleDefinition, AngleMeasurement, AngleStatus } from '../types/protocol'

export interface AngleCell {
  definition: AngleDefinition
  measurement: AngleMeasurement | null
}

export interface AngleRow {
  joint: string
  label: string
  left: AngleCell | null
  right: AngleCell | null
}

const STATUS_TEXT: Record<AngleStatus, string> = {
  ok: '',
  no_person: '—',
  low_visibility: 'not visible',
  out_of_frame: 'out of frame',
  degenerate: 'unclear',
  unavailable: 'unavailable',
}

/** Short reason shown instead of a number when an angle is not measurable. */
export function angleStatusText(m: AngleMeasurement | null): string {
  return m ? STATUS_TEXT[m.status] : '—'
}

export function formatAngle(m: AngleMeasurement | null): string | null {
  return m?.status === 'ok' && m.value_deg !== null ? `${Math.round(m.value_deg)}°` : null
}

/** Pair definitions with this frame's measurements, one row per joint (L/R). */
export function groupAngles(definitions: AngleDefinition[], measurements: AngleMeasurement[]): AngleRow[] {
  const byId = new Map(measurements.map((m) => [m.id, m]))
  const rows = new Map<string, AngleRow>()
  for (const d of definitions) {
    const row = rows.get(d.joint) ?? {
      joint: d.joint,
      label: d.label.replace(/^(Left|Right)\s+/, ''),
      left: null,
      right: null,
    }
    row[d.side] = { definition: d, measurement: byId.get(d.id) ?? null }
    rows.set(d.joint, row)
  }
  return [...rows.values()]
}
