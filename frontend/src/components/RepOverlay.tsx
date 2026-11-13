import { phaseLabel } from '../services/exercise'
import type { ActiveExercise, ExerciseState } from '../types/protocol'

/** Large rep counter over the camera view, readable from a distance. */
export function RepOverlay({ active, live }: { active: ActiveExercise | null; live: ExerciseState | null }) {
  if (!active || live?.selection_id !== active.selection_id) return null
  const perSet = active.exercise.dosage.reps_per_set
  return (
    <div className="rep-overlay" aria-hidden="true">
      <div className="rep-overlay-count">
        {live.reps}
        {perSet ? <span className="rep-overlay-of"> / {perSet}</span> : null}
      </div>
      <div className="rep-overlay-phase">{phaseLabel(live.phase)}</div>
    </div>
  )
}
