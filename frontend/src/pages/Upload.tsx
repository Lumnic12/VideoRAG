import { useState, useRef, type DragEvent, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadVideo } from '../lib/api'
import { useJobSocket, type JobUpdate } from '../hooks/useJobSocket'

type Phase = 'idle' | 'uploading' | 'processing' | 'done' | 'error'

const PIPELINE_STEPS = [
  { pct: 10,  label: 'Extracting keyframes via SSIM…' },
  { pct: 30,  label: 'Keyframes extracted' },
  { pct: 40,  label: 'Extracting audio track…' },
  { pct: 70,  label: 'VLM analysis + transcription…' },
  { pct: 85,  label: 'Structuring transcript with LLM…' },
  { pct: 90,  label: 'Indexing into FAISS RAG…' },
  { pct: 100, label: 'Done! ✓' },
]

function stepForProgress(pct: number): string {
  for (const s of [...PIPELINE_STEPS].reverse()) {
    if (pct >= s.pct) return s.label
  }
  return 'Queued — waiting for worker…'
}

export function Upload() {
  const navigate = useNavigate()
  const [phase, setPhase] = useState<Phase>('idle')
  const [file, setFile] = useState<File | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [log, setLog] = useState<string[]>([])
  const [keyframeCount, setKeyframeCount] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const logRef = useRef<HTMLDivElement>(null)

  const addLog = (msg: string) => {
    setLog(prev => [...prev.slice(-50), msg])
    setTimeout(() => logRef.current?.scrollTo({ top: 99999, behavior: 'smooth' }), 50)
  }

  // WebSocket progress streaming
  useJobSocket(phase === 'processing' ? taskId : null, {
    onUpdate(u: JobUpdate) {
      setProgress(u.progress)
      const step = u.message ?? stepForProgress(u.progress)
      addLog(`[${u.progress}%] ${step}`)
    },
    onDone(u: JobUpdate) {
      setProgress(100)
      setKeyframeCount(u.keyframe_count ?? null)
      setPhase('done')
      addLog(`[100%] Pipeline complete — ${u.keyframe_count ?? 0} keyframes extracted`)
    },
    onError(u: JobUpdate) {
      setPhase('error')
      setError(u.error ?? 'Processing failed')
      addLog(`[ERROR] ${u.error ?? 'Unknown error'}`)
    },
  })

  const handleFile = (f: File) => {
    if (!f.type.startsWith('video/')) {
      setError('Please upload a video file (mp4, mkv, avi, webm…)')
      return
    }
    setFile(f)
    setError(null)
  }

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) handleFile(e.target.files[0])
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files?.[0]) handleFile(e.dataTransfer.files[0])
  }

  const startUpload = async () => {
    if (!file) return
    try {
      setPhase('uploading')
      setProgress(5)
      setError(null)
      setLog([])
      addLog('Uploading video to server…')

      const result = await uploadVideo(file)
      const id = result.task_id
      setTaskId(id)
      localStorage.setItem('videorag_last_task_id', id)
      setProgress(10)
      setPhase('processing')
      addLog(`Task enqueued — ID: ${id}`)
      addLog('Connecting to pipeline stream…')
    } catch {
      setPhase('error')
      setError('Upload failed — is the backend running on :8000?')
    }
  }

  const reset = () => {
    setPhase('idle')
    setFile(null)
    setTaskId(null)
    setProgress(0)
    setLog([])
    setKeyframeCount(null)
    setError(null)
  }

  return (
    <div className="page-content animate-fadein">
      <div className="page-header">
        <h1 className="page-title">Upload Video</h1>
        <p className="page-subtitle">
          Drop a video file to extract keyframes via SSIM and index it for RAG queries.
        </p>
      </div>

      {/* ── Idle: drop zone ── */}
      {phase === 'idle' && (
        <>
          <div
            id="upload-drop-zone"
            className={`drop-zone${dragOver ? ' drag-over' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            aria-label="Click or drop video file"
          >
            <span className="drop-zone-icon">{file ? '✅' : '📁'}</span>
            <p className="drop-zone-title">{file ? file.name : 'Drop your video here'}</p>
            <p className="drop-zone-sub">
              {file
                ? `${(file.size / 1024 / 1024).toFixed(1)} MB — ready to upload`
                : 'MP4, MKV, AVI, WebM · Max 500 MB'}
            </p>
          </div>

          <input id="file-input" ref={fileInputRef} type="file" accept="video/*"
            style={{ display: 'none' }} onChange={onChange} />

          {error && (
            <div className="badge badge-error" style={{ marginTop: '0.75rem', padding: '0.5rem 1rem' }}>
              ⚠ {error}
            </div>
          )}

          <div className="flex gap-3" style={{ marginTop: '1.5rem' }}>
            <button id="upload-submit-btn" className="btn btn-primary"
              disabled={!file} onClick={startUpload}>
              🚀 Start Upload & Process
            </button>
            {file && <button id="upload-clear-btn" className="btn btn-ghost" onClick={reset}>Clear</button>}
          </div>

          <div className="grid-2" style={{ marginTop: '2rem' }}>
            <div className="card">
              <h3 style={{ marginBottom: '0.75rem' }}>⚡ SSIM Keyframe Extraction</h3>
              <p className="text-sm">
                Structural Similarity Index detects scene changes and extracts only the most visually
                distinct frames — reducing noise and processing time.
              </p>
            </div>
            <div className="card">
              <h3 style={{ marginBottom: '0.75rem' }}>🧠 RAG Indexing</h3>
              <p className="text-sm">
                Keyframe descriptions and transcript chunks are embedded and stored in a local FAISS
                index for fast semantic retrieval.
              </p>
            </div>
          </div>
        </>
      )}

      {/* ── Uploading / Processing ── */}
      {(phase === 'uploading' || phase === 'processing') && (
        <div className="card animate-fadein" id="upload-progress-card">

          {/* Header */}
          <div className="flex items-center gap-3" style={{ marginBottom: '1.25rem' }}>
            <div className="spinner" />
            <span style={{ fontWeight: 600 }}>
              {phase === 'uploading' ? 'Uploading…' : 'Processing pipeline…'}
            </span>
            {taskId && (
              <span className="badge badge-info" style={{ marginLeft: 'auto', fontSize: '0.7rem' }}>
                {taskId.slice(0, 8)}…
              </span>
            )}
          </div>

          {/* Progress bar */}
          <div className="progress-bar" style={{ marginBottom: '1rem' }}>
            <div className="progress-fill" style={{
              width: `${progress}%`,
              transition: 'width 0.4s ease',
            }} />
          </div>
          <div className="flex items-center justify-between text-sm text-muted" style={{ marginBottom: '1.25rem' }}>
            <span>{stepForProgress(progress)}</span>
            <span style={{ fontWeight: 700, color: 'var(--text-accent)' }}>{progress}%</span>
          </div>

          {/* Pipeline steps indicator */}
          <div className="flex gap-2" style={{ marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            {PIPELINE_STEPS.map((s) => (
              <div
                key={s.pct}
                style={{
                  padding: '0.25rem 0.6rem',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.7rem',
                  fontWeight: 600,
                  background: progress >= s.pct
                    ? 'rgba(52,211,153,0.15)' : 'rgba(255,255,255,0.04)',
                  color: progress >= s.pct ? '#34d399' : 'var(--text-muted)',
                  border: `1px solid ${progress >= s.pct ? 'rgba(52,211,153,0.3)' : 'rgba(255,255,255,0.06)'}`,
                  transition: 'all 0.3s ease',
                }}
              >
                {s.pct}% {progress >= s.pct ? '✓' : '○'}
              </div>
            ))}
          </div>

          {/* Live log */}
          {log.length > 0 && (
            <div
              ref={logRef}
              className="code-block"
              style={{
                maxHeight: 180, overflowY: 'auto', fontSize: '0.72rem',
                lineHeight: 1.7, fontFamily: '"JetBrains Mono", monospace',
              }}
            >
              {log.map((l, i) => <div key={i} style={{ color: i === log.length - 1 ? 'var(--text-accent)' : 'var(--text-muted)' }}>{l}</div>)}
            </div>
          )}
        </div>
      )}

      {/* ── Done ── */}
      {phase === 'done' && taskId && (
        <div className="card animate-fadein" id="upload-done-card" style={{ borderColor: 'rgba(52,211,153,0.3)' }}>
          <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>✅</div>
          <h2 style={{ marginBottom: '0.5rem' }}>Processing Complete!</h2>
          <p className="text-sm text-muted" style={{ marginBottom: '0.75rem' }}>
            <strong style={{ color: 'var(--text-accent)' }}>{keyframeCount ?? 0} keyframes</strong> extracted
            and indexed — ready for querying.
          </p>
          <div className="code-block" style={{ marginBottom: '1.25rem', fontSize: '0.78rem' }}>
            Task ID: <span style={{ color: 'var(--text-accent)' }}>{taskId}</span>
          </div>
          <div className="flex gap-3" style={{ flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary"
              id="view-results-btn"
              onClick={() => navigate(`/results/${taskId}`)}
            >
              🎞️ View Results
            </button>
            <a href="/query" className="btn btn-secondary" id="ask-question-btn">🔍 Ask a Question</a>
            <button className="btn btn-ghost" onClick={reset}>Upload Another</button>
          </div>
        </div>
      )}

      {/* ── Error ── */}
      {phase === 'error' && (
        <div className="card animate-fadein" id="upload-error-card" style={{ borderColor: 'rgba(248,113,113,0.3)' }}>
          <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>❌</div>
          <h2 style={{ marginBottom: '0.5rem' }}>Processing Failed</h2>
          <p className="text-sm" style={{ color: '#f87171', marginBottom: '1.5rem' }}>{error}</p>
          {log.length > 0 && (
            <div className="code-block" style={{ maxHeight: 120, overflowY: 'auto', fontSize: '0.72rem', marginBottom: '1rem' }}>
              {log.map((l, i) => <div key={i}>{l}</div>)}
            </div>
          )}
          <button className="btn btn-secondary" onClick={reset}>Try Again</button>
        </div>
      )}
    </div>
  )
}
