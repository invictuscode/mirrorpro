import { Panel } from './Panels'
import { angleStatusText, formatAngle, groupAngles, type AngleCell } from '../services/angles'
import type { AngleDefinition, FrameMessage } from '../types/protocol'

function Cell({ cell }: { cell: AngleCell | null }) {
  const m = cell?.measurement ?? null
  const value = formatAngle(m)
  const tooltip = m
    ? `${cell?.definition.description}\nraw ${m.raw_deg ?? '—'}°, confidence ${m.confidence?.toFixed(2) ?? '—'}`
    : undefined
  return (
    <td className={`angle-cell ${value ? '' : 'invalid'}`} title={tooltip}>
      {value ?? angleStatusText(m)}
    </td>
  )
}

export function AnglesPanel({
  definitions,
  message,
}: {
  definitions: AngleDefinition[]
  message: FrameMessage | null
}) {
  const rows = groupAngles(definitions, message?.angles ?? [])
  // Per frame: an active exercise may use a different space from the default.
  const space = message?.angle_space === 'world' ? '3D model estimate' : '2D image'
  return (
    <Panel title="Estimated joint angles">
      <table className="angle-table">
        <thead>
          <tr>
            <th />
            <th>Left</th>
            <th>Right</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.joint}>
              <th scope="row">{row.label}</th>
              <Cell cell={row.left} />
              <Cell cell={row.right} />
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">
        Experimental camera estimates ({space}), not clinical measurements. Values are hidden when the joint is not
        clearly tracked. Hover a value for its definition.
      </p>
    </Panel>
  )
}
