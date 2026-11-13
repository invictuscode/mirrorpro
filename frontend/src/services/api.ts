import type {
  ActiveExercise,
  AngleDefinition,
  ExerciseDefinition,
  ExerciseSummary,
  RepCountingOverrides,
  SessionView,
  Side,
  StartSessionRequest,
  StatusMessage,
  Topology,
} from '../types/protocol'

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit, acceptStatuses: number[] = []): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (err) {
    throw new ApiError(`Backend not reachable (${err instanceof Error ? err.message : String(err)})`)
  }
  if (!res.ok && !acceptStatuses.includes(res.status)) {
    throw new ApiError(await errorMessage(res, `${init?.method ?? 'GET'} ${path} failed: HTTP ${res.status}`))
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// A failed start returns 503 with a StatusMessage describing why; surface that
// status rather than a generic HTTP error.
export const startCamera = () => request<StatusMessage>('/api/camera/start', { method: 'POST' }, [503])
export const stopCamera = () => request<StatusMessage>('/api/camera/stop', { method: 'POST' })
export const getTopology = () => request<Topology>('/api/pose/topology')
export const getAngleDefinitions = () => request<AngleDefinition[]>('/api/angles/definitions')

export const listExercises = () => request<ExerciseSummary[]>('/api/exercises')
export const getExercise = (id: string) => request<ExerciseDefinition>(`/api/exercises/${encodeURIComponent(id)}`)
export const getActiveExercise = () => request<ActiveExercise | null>('/api/exercise/active')
export const resetExercise = () => request<ActiveExercise>('/api/exercise/active/reset', { method: 'POST' })
export const clearExercise = () => request<void>('/api/exercise/active', { method: 'DELETE' })

export function selectExercise(exerciseId: string, side: Side | null, overrides: RepCountingOverrides) {
  return request<ActiveExercise>('/api/exercise/active', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ exercise_id: exerciseId, side, overrides }),
  })
}

/** FastAPI errors carry `detail` (a string, or a list of validation errors). */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ')
    }
  } catch {
    // Not JSON: fall through to the generic message.
  }
  return fallback
}

const post = <T,>(path: string) => request<T>(path, { method: 'POST' })

export const startSession = (body: StartSessionRequest) =>
  request<SessionView>('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
export const pauseSession = () => post<SessionView>('/api/session/pause')
export const resumeSession = () => post<SessionView>('/api/session/resume')
export const advanceSession = () => post<SessionView>('/api/session/advance')
export const endSession = () => post<SessionView>('/api/session/end')
export const dismissSession = () => request<void>('/api/session', { method: 'DELETE' })
