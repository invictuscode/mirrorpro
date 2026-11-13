import { useMemo, useRef, useState, type PointerEvent } from 'react'

import type { DetectedRep } from '../../types/authoring'

/** Palette validated with the dataviz validator against the dark panel
 * surface (#12161b): lightness, chroma, CVD ΔE 9.4, normal-vision ΔE 26.5,
 * contrast ≥ 3:1 — all pass. */
const COLOR = { angle: '#3987e5', start: '#d95926', target: '#199e70' }

const W = 720
const H = 260
const M = { top: 12, right: 92, bottom: 34, left: 44 } // bottom includes the x-axis band

interface Props {
  title: string
  tMs: number[]
  deg: (number | null)[]
  reps: DetectedRep[]
  startDeg: number | null
  targetDeg: number | null
}

/** Driving angle over the demonstration, with the current start/target
 * thresholds and the detected repetitions. Thresholds follow the parameter
 * editor, so the therapist sees how a change relates to the demonstration. */
export function DemoChart(props: Props) {
  if (!props.deg.some((v) => v !== null)) {
    return <p className="hint">No tracked angle data to chart.</p>
  }
  return <Chart {...props} />
}

function Chart({ title, tMs, deg, reps, startDeg, targetDeg }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)

  const { x, y, yTicks, xTicks, path } = useMemo(() => {
    const vals = deg.filter((v): v is number => v !== null)
    const extra = [startDeg, targetDeg].filter((v): v is number => v !== null)
    const lo = Math.max(0, Math.floor((Math.min(...vals, ...extra) - 10) / 30) * 30)
    const hi = Math.min(180, Math.ceil((Math.max(...vals, ...extra) + 10) / 30) * 30)
    const tMax = Math.max(1, tMs.at(-1) ?? 1)
    const x = (t: number) => M.left + (t / tMax) * (W - M.left - M.right)
    const y = (v: number) => M.top + (1 - (v - lo) / Math.max(1, hi - lo)) * (H - M.top - M.bottom)
    const yTicks: number[] = []
    for (let v = lo; v <= hi; v += 30) yTicks.push(v)
    const stepS = tMax > 40_000 ? 10 : tMax > 15_000 ? 5 : 2
    const xTicks: number[] = []
    for (let s = 0; s * 1000 <= tMax; s += stepS) xTicks.push(s)
    // Break the line where the angle was not tracked (null), never interpolate visually.
    let d = ''
    let pen = false
    deg.forEach((v, i) => {
      if (v === null) {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${x(tMs[i] ?? 0).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    })
    return { x, y, yTicks, xTicks, path: d }
  }, [tMs, deg, startDeg, targetDeg])

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const svg = svgRef.current
    if (!svg || tMs.length === 0) return
    const r = svg.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * W
    const t = ((px - M.left) / (W - M.left - M.right)) * (tMs.at(-1) ?? 1)
    // Snap to the nearest sample (binary search).
    let lo = 0
    let hi = tMs.length - 1
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if ((tMs[mid] ?? 0) < t) lo = mid + 1
      else hi = mid
    }
    const prev = Math.max(0, lo - 1)
    setHover(Math.abs((tMs[prev] ?? 0) - t) < Math.abs((tMs[lo] ?? 0) - t) ? prev : lo)
  }

  const hv = hover === null ? null : { t: tMs[hover] ?? 0, v: deg[hover] ?? null }
  const hoverRep = hv ? reps.findIndex((r) => hv.t >= r.start_ms && hv.t <= r.end_ms) : -1

  return (
    <figure className="t-chart">
      <figcaption className="t-chart-title">{title}</figcaption>
      <ul className="t-legend" aria-label="Legend">
        <li>
          <LineKey color={COLOR.angle} /> Angle (camera estimate)
        </li>
        {startDeg !== null && (
          <li>
            <LineKey color={COLOR.start} /> Start threshold
          </li>
        )}
        {targetDeg !== null && (
          <li>
            <LineKey color={COLOR.target} /> Target threshold
          </li>
        )}
        {reps.length > 0 && (
          <li>
            <span className="t-key-rect" /> Detected repetition
          </li>
        )}
      </ul>
      <div className="t-chart-wrap">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}; data table below`}>
          {reps.map((r, i) => (
            <rect
              key={i}
              x={x(r.start_ms)}
              y={M.top}
              width={Math.max(1, x(r.end_ms) - x(r.start_ms))}
              height={H - M.top - M.bottom}
              className="t-rep-band"
            />
          ))}
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} className="t-grid" />
              <text x={M.left - 8} y={y(v)} className="t-axis" textAnchor="end" dominantBaseline="middle">
                {v}°
              </text>
            </g>
          ))}
          {xTicks.map((s) => (
            <text key={s} x={x(s * 1000)} y={H - M.bottom + 18} className="t-axis" textAnchor="middle">
              {s}s
            </text>
          ))}
          <line x1={M.left} x2={W - M.right} y1={H - M.bottom} y2={H - M.bottom} className="t-axis-line" />
          {startDeg !== null && <Threshold y={y(startDeg)} color={COLOR.start} label={`start ${startDeg}°`} />}
          {targetDeg !== null && <Threshold y={y(targetDeg)} color={COLOR.target} label={`target ${targetDeg}°`} />}
          <path d={path} fill="none" stroke={COLOR.angle} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hv && (
            <g pointerEvents="none">
              <line x1={x(hv.t)} x2={x(hv.t)} y1={M.top} y2={H - M.bottom} className="t-crosshair" />
              {hv.v !== null && <circle cx={x(hv.t)} cy={y(hv.v)} r={4.5} fill={COLOR.angle} className="t-dot" />}
            </g>
          )}
          <rect
            x={M.left}
            y={M.top}
            width={W - M.left - M.right}
            height={H - M.top - M.bottom}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          />
        </svg>
        {hv && (
          <div className="t-tooltip" style={{ left: `${(x(hv.t) / W) * 100}%` }} role="status">
            <strong>{hv.v === null ? 'not tracked' : `${hv.v.toFixed(1)}°`}</strong>
            <span>
              {(hv.t / 1000).toFixed(1)} s{hoverRep >= 0 ? ` · repetition ${hoverRep + 1}` : ''}
            </span>
          </div>
        )}
      </div>
      <details className="t-data">
        <summary>Show data</summary>
        <table>
          <thead>
            <tr>
              <th>Time (s)</th>
              <th>Angle (°)</th>
            </tr>
          </thead>
          <tbody>
            {tMs.map((t, i) => (
              <tr key={t}>
                <td>{(t / 1000).toFixed(2)}</td>
                <td>{deg[i] === null ? 'not tracked' : deg[i]?.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}

function LineKey({ color }: { color: string }) {
  return (
    <svg width="18" height="8" aria-hidden="true">
      <line x1="1" x2="17" y1="4" y2="4" stroke={color} strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function Threshold({ y, color, label }: { y: number; color: string; label: string }) {
  return (
    <g>
      <line x1={M.left} x2={W - M.right} y1={y} y2={y} stroke={color} strokeWidth={1.5} />
      <line x1={W - M.right + 6} x2={W - M.right + 16} y1={y} y2={y} stroke={color} strokeWidth={2} strokeLinecap="round" />
      <text x={W - M.right + 20} y={y} className="t-direct-label" dominantBaseline="middle">
        {label}
      </text>
    </g>
  )
}
