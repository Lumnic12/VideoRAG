import { useState, useEffect, useRef, useCallback } from 'react'

export interface JobUpdate {
  type: 'progress' | 'done' | 'error'
  status: string
  progress: number
  message?: string
  result?: unknown
  keyframe_count?: number
  error?: string
}

interface Options {
  onUpdate?: (u: JobUpdate) => void
  onDone?: (u: JobUpdate) => void
  onError?: (u: JobUpdate) => void
}

/**
 * Connects to ws://localhost:8000/ws/jobs/{jobId} and streams
 * pipeline progress updates in real time.
 * Falls back to HTTP polling if WebSocket fails.
 */
export function useJobSocket(jobId: string | null, opts: Options = {}) {
  const [latest, setLatest] = useState<JobUpdate | null>(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const { onUpdate, onDone, onError } = opts

  const cleanup = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
    setConnected(false)
  }, [])

  useEffect(() => {
    if (!jobId) return
    cleanup()

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${proto}://${window.location.host}/ws/jobs/${jobId}`
    let ws: WebSocket

    try {
      ws = new WebSocket(wsUrl)
      wsRef.current = ws
    } catch {
      startPolling(jobId)
      return
    }

    ws.onopen = () => setConnected(true)

    ws.onmessage = (evt) => {
      try {
        const update: JobUpdate = JSON.parse(evt.data)
        setLatest(update)
        onUpdate?.(update)
        if (update.type === 'done') {
          onDone?.(update)
          cleanup()
        } else if (update.type === 'error') {
          onError?.(update)
          cleanup()
        }
      } catch { /* ignore malformed frames */ }
    }

    ws.onerror = () => {
      // WebSocket failed — fall back to HTTP polling
      ws.close()
      startPolling(jobId)
    }

    ws.onclose = () => setConnected(false)

    return cleanup
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  function startPolling(id: string) {
    setConnected(true)
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/tasks/${id}`)
        if (!res.ok) return
        const data = await res.json()
        const update: JobUpdate = {
          type: data.status === 'done' ? 'done'
              : data.status === 'failed' ? 'error'
              : 'progress',
          status: data.status,
          progress: data.progress ?? 0,
          message: data.status,
          result: data.result,
          keyframe_count: data.keyframe_count,
          error: data.error,
        }
        setLatest(update)
        onUpdate?.(update)
        if (update.type === 'done') { onDone?.(update); cleanup() }
        if (update.type === 'error') { onError?.(update); cleanup() }
      } catch { /* ignore */ }
    }, 1500)
  }

  return { latest, connected }
}
