import { useCallback, useEffect, useRef, useState } from 'react'

import {
  clearExercise,
  getActiveExercise,
  listExercises,
  resetExercise,
  selectExercise,
} from '../services/api'
import type { ActiveExercise, ExerciseSummary, RepCountingOverrides, Side } from '../types/protocol'

export interface Exercises {
  library: ExerciseSummary[]
  active: ActiveExercise | null
  busy: boolean
  error: string | null
  select: (id: string, side: Side | null, overrides: RepCountingOverrides) => Promise<void>
  reset: () => Promise<void>
  clear: () => Promise<void>
}

/** Exercise library and the backend's active selection. Re-syncs when the
 * backend connection (re)opens, and when the stream shows a selection this page
 * doesn't know about (changed by another client, or cleared).
 *
 * `liveSelectionId`: the stream's current selection id, null if frames show no
 * exercise, undefined if there are no frames to judge from. */
export function useExercises(connected: boolean, liveSelectionId: number | null | undefined): Exercises {
  const [library, setLibrary] = useState<ExerciseSummary[]>([])
  const [active, setActive] = useState<ActiveExercise | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!connected) return
    Promise.all([listExercises(), getActiveExercise()])
      .then(([lib, act]) => {
        setLibrary(lib)
        setActive(act)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [connected])

  const syncingFor = useRef<number | null | undefined>(undefined)
  useEffect(() => {
    if (!connected || busy || liveSelectionId === undefined) return
    const known = active?.selection_id ?? null
    if (liveSelectionId === known || syncingFor.current === liveSelectionId) return
    syncingFor.current = liveSelectionId
    getActiveExercise()
      .then(setActive)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [connected, busy, liveSelectionId, active])

  const run = useCallback(async (action: () => Promise<ActiveExercise | null>) => {
    setBusy(true)
    setError(null)
    try {
      setActive(await action())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [])

  return {
    library,
    active,
    busy,
    error,
    select: (id, side, overrides) => run(() => selectExercise(id, side, overrides)),
    reset: () => run(resetExercise),
    clear: () => run(async () => (await clearExercise(), null)),
  }
}
