import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error('API error:', err)
    return Promise.reject(err)
  }
)

// ── Types (mirror backend schemas) ────────────────────────────────────────────

export interface QueryRequest {
  question: string
  video_id?: string
  video_ids?: string[]
}

export interface QuerySource {
  video_id: string
  timestamp: number
  timestamp_sec: number  // alias for convenience
  chunk_text: string
  text: string           // alias for convenience
  score: number
}

export interface QueryResult {
  answer: string
  sources: QuerySource[]
  latency_ms: number
}

export interface UploadStatus {
  task_id: string
  status: 'queued' | 'processing' | 'done' | 'failed' | 'error'
  progress?: number
  keyframe_count?: number
  message?: string
  result?: unknown
  error?: string
}

export interface KeyframeInfo {
  index: number
  frame_number: number
  timestamp_sec: number
  ssim_delta: number
  image_url: string
  image_b64?: string | null
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  redis: boolean
  celery: boolean
  version: string
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const healthCheck = () =>
  api.get<HealthResponse>('/health').then((r) => r.data)

export const queryVideo = (data: QueryRequest) =>
  api.post<QueryResult>('/query', data).then((r) => r.data)

/** Upload a video file — field name must match backend: 'video' */
export const uploadVideo = (file: File) => {
  const form = new FormData()
  form.append('video', file)          // backend File(...) param name is 'video'
  return api
    .post<UploadStatus>('/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

/** Poll job progress + result */
export const getTaskStatus = (taskId: string) =>
  api.get<UploadStatus>(`/tasks/${taskId}`).then((r) => r.data)

/** Fetch list of extracted keyframe images for a completed job */
export const getKeyframes = (taskId: string) =>
  api.get<KeyframeInfo[]>(`/keyframes/${taskId}`).then((r) => r.data)

export interface StatsResponse {
  videos_indexed: number
  keyframes_extracted: number
  jobs_in_progress: number
}

export const getStats = () =>
  api.get<StatsResponse>('/stats').then((r) => r.data)

export default api

