import { ApiError } from './api'
import type {
  AnalysisResult,
  AnalyzeRequest,
  CustomExercise,
  DemonstrationInfo,
  DraftFields,
  LiveRecordingStatus,
} from '../types/authoring'

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (err) {
    throw new ApiError(`Backend not reachable (${err instanceof Error ? err.message : String(err)})`)
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ')
    } catch {
      // non-JSON error body: keep the status text
    }
    throw new ApiError(detail)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const liveStatus = () => call<LiveRecordingStatus>('/api/demonstrations/live')
export const startLiveRecording = () => call<LiveRecordingStatus>('/api/demonstrations/live/start', { method: 'POST' })
export const stopLiveRecording = () => call<DemonstrationInfo>('/api/demonstrations/live/stop', { method: 'POST' })
export const cancelLiveRecording = () => call<void>('/api/demonstrations/live/cancel', { method: 'POST' })

/** The file is sent as the raw request body, processed locally, then deleted by the backend. */
export const uploadDemonstration = (file: File) =>
  call<DemonstrationInfo>('/api/demonstrations/upload', {
    method: 'POST',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  })

export const analyzeDemonstration = (demoId: string, req: AnalyzeRequest = {}) =>
  call<AnalysisResult>(`/api/demonstrations/${encodeURIComponent(demoId)}/analyze`, json('POST', req))

export const listCustomExercises = () => call<CustomExercise[]>('/api/custom-exercises')
export const createCustomExercise = (fields: DraftFields, demoId: string | null, storeAngleData: boolean) =>
  call<CustomExercise>('/api/custom-exercises', json('POST', { fields, demo_id: demoId, store_angle_data: storeAngleData }))
export const updateCustomExercise = (id: string, fields: DraftFields) =>
  call<CustomExercise>(`/api/custom-exercises/${encodeURIComponent(id)}`, json('PUT', fields))
export const approveCustomExercise = (id: string, reviewer: string, attestation: boolean) =>
  call<CustomExercise>(`/api/custom-exercises/${encodeURIComponent(id)}/approve`, json('POST', { reviewer, attestation }))
export const archiveCustomExercise = (id: string) =>
  call<CustomExercise>(`/api/custom-exercises/${encodeURIComponent(id)}/archive`, { method: 'POST' })
export const deleteCustomExercise = (id: string) =>
  call<void>(`/api/custom-exercises/${encodeURIComponent(id)}`, { method: 'DELETE' })
