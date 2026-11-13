import type { RefObject } from 'react'

import type { GuideSpec, Highlight } from '../guideOverlay'
import { PoseCanvas } from '../PoseCanvas'
import { StatusOverlay } from '../StatusOverlay'
import type { DecodedFrame } from '../../services/streamClient'
import type { TrackingStatus } from '../../services/trackingStatus'
import type { AngleDefinition, Topology } from '../../types/protocol'

/**
 * How the camera half of the split screen is drawn:
 * - `video`: camera image with all body points (laptop/TV display)
 * - `skeleton`: body points only, on black — behind a two-way mirror the
 *   reflection replaces the video
 */
export type CameraStyle = 'video' | 'skeleton'

export const CAMERA_STYLE_LABEL: Record<CameraStyle, string> = {
  video: 'Video',
  skeleton: 'Points only',
}

interface Props {
  frameRef: RefObject<DecodedFrame | null>
  topology: Topology | null
  angleDefinitions: AngleDefinition[]
  style: CameraStyle
  tracking: TrackingStatus
  guides?: GuideSpec[]
  highlights?: Highlight[]
}

export function MirrorStage({ frameRef, topology, angleDefinitions, style, tracking, guides, highlights }: Props) {
  return (
    <div className="m-stage">
      <PoseCanvas
        frameRef={frameRef}
        topology={topology}
        mirrored
        showVideo={style === 'video'}
        angleDefinitions={angleDefinitions}
        showAngles
        {...(guides ? { guides } : {})}
        {...(highlights ? { highlights } : {})}
      />
      <StatusOverlay status={tracking} />
    </div>
  )
}
