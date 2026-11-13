import { useEffect, useState } from 'react'

import { getExercise } from '../services/api'
import type { ExerciseDefinition } from '../types/protocol'

/** Full definition for an exercise id (null while loading or if id is null). */
export function useExerciseDefinition(id: string | null): { definition: ExerciseDefinition | null; error: string | null } {
  const [definition, setDefinition] = useState<ExerciseDefinition | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setDefinition(null)
    setError(null)
    if (!id) return
    let cancelled = false
    getExercise(id)
      .then((d) => !cancelled && setDefinition(d))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [id])
  return { definition, error }
}
