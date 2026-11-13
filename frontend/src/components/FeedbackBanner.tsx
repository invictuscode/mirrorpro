import type { ActiveExercise, ExerciseState } from '../types/protocol'

/**
 * The single current feedback message, large and high-contrast for reading at
 * a distance. Keyed by `seq` so each new message re-runs the entrance
 * animation; announced politely to screen readers.
 */
export function FeedbackBanner({ active, live }: { active: ActiveExercise | null; live: ExerciseState | null }) {
  const message = active && live?.selection_id === active.selection_id ? live.feedback.message : null
  return (
    <div className="feedback-slot" role="status" aria-live="polite" aria-atomic="true">
      {message && (
        <div key={message.seq} className={`feedback-banner fb-${message.category}`}>
          {message.text}
        </div>
      )}
    </div>
  )
}
