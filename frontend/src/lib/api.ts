import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 600000,
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

export interface ChatHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface QueryRequest {
  question: string
  video_id?: string
  video_ids?: string[]
  chat_history?: ChatHistoryMessage[]
}

export interface QuerySource {
  video_id: string
  timestamp: number
  timestamp_sec: number  // alias for convenience
  chunk_text: string
  text: string           // alias for convenience
  score: number
  type?: string          // 'keyframe' | 'transcript' | 'transcript_window'
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
      timeout: 600000, // 10 minute timeout for large videos
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

export interface VideoListItem {
  job_id: string
  filename: string
  status: string
  keyframe_count: number
  progress: number
  has_audio?: boolean
}

export const listVideos = () =>
  api.get<{ videos: VideoListItem[] }>('/videos').then((r) => r.data.videos)

export const deleteVideo = (jobId: string) =>
  api.delete(`/videos/${jobId}`).then((r) => r.data)

/** Get audio stream URL for a job — returns a URL string, not fetched data */
export const getAudioUrl = (jobId: string): string => `/api/v1/audio/${jobId}`

/** Re-seed Redis from filesystem (call after backend restart) */
export const reseedVideos = () =>
  api.get<{ seeded: number; message: string }>('/videos/reseed').then((r) => r.data)

/** Re-index an already-processed video into FAISS (fixes stale cache) */
export const reindexVideo = (jobId: string) =>
  api.post<{ status: string; keyframes: number; transcript_segments: number }>(
    `/videos/${jobId}/reindex`
  ).then((r) => r.data)

export default api
