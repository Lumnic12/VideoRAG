import { useState, useEffect } from 'react'
import { getKeyframes, type KeyframeInfo } from '../lib/api'

function formatSec(s: number) {
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(1).padStart(4, '0')
  return `${m}:${sec}`
}

export function Keyframes() {
  const [taskId, setTaskId] = useState('')
  const [inputVal, setInputVal] = useState('')
  const [keyframes, setKeyframes] = useState<KeyframeInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<KeyframeInfo | null>(null)

  // Load from localStorage if we have a saved task_id
  useEffect(() => {
    const saved = localStorage.getItem('videorag_last_task_id')
    if (saved) {
      setInputVal(saved)
      setTaskId(saved)
    }
  }, [])

  useEffect(() => {
    if (!taskId) return
    setLoading(true)
    setError(null)
    getKeyframes(taskId)
      .then((kfs) => {
        setKeyframes(kfs)
        setLoading(false)
      })
      .catch((err) => {
        if (err?.response?.status === 404) {
          setError('No keyframes found for this task ID — has the video finished processing?')
        } else {
          setError('Could not load keyframes. Check backend connection.')
        }
        setKeyframes([])
        setLoading(false)
      })
  }, [taskId])

  const load = () => {
    if (!inputVal.trim()) return
    localStorage.setItem('videorag_last_task_id', inputVal.trim())
    setTaskId(inputVal.trim())
    setSelected(null)
  }

  return (
    <div className="page-content animate-fadein">
      <div className="page-header">
        <h1 className="page-title">Keyframe Gallery</h1>
        <p className="page-subtitle">
          Visually distinct frames extracted via SSIM scene-change detection.
        </p>
      </div>

      {/* Task ID input */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="input-group" style={{ marginBottom: '1rem' }}>
          <label className="input-label" htmlFor="task-id-input">Task ID (from Upload)</label>
          <div className="flex gap-3">
            <input
              id="task-id-input"
              className="input"
              placeholder="Paste your task_id here…"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && load()}
            />
            <button
              id="load-keyframes-btn"
              className="btn btn-primary"
              onClick={load}
              disabled={!inputVal.trim()}
            >
              Load
            </button>
          </div>
        </div>

      </div>

      {/* States */}
      {!taskId && (
        <div className="empty-state">
          <span className="empty-icon">🎞️</span>
          <h2 style={{ fontSize: '1.2rem' }}>No task loaded</h2>
          <p className="text-sm text-muted">Upload a video and paste the task_id above.</p>
          <a href="/upload" className="btn btn-primary">📤 Upload a Video</a>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-3" style={{ padding: '3rem 0' }}>
          <div className="spinner" />
          <span className="text-muted">Loading keyframes…</span>
        </div>
      )}

      {error && (
        <div className="card" style={{ borderColor: 'rgba(248,113,113,0.3)', color: '#f87171' }}>
          ⚠ {error}
        </div>
      )}

      {/* Stats bar */}
      {keyframes.length > 0 && !loading && (
        <>
          <div className="flex items-center justify-between" style={{ marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
            <div className="flex gap-3" style={{ flexWrap: 'wrap' }}>
              <span className="badge badge-success">✓ {keyframes.length} keyframes</span>
              <span className="badge badge-info">
                Duration: {formatSec(keyframes[keyframes.length - 1]?.timestamp_sec ?? 0)}
              </span>
              <span className="badge badge-purple">
                Avg SSIM Δ: {(keyframes.reduce((a, k) => a + k.ssim_delta, 0) / keyframes.length).toFixed(3)}
              </span>
            </div>
          </div>

          <div className="keyframe-grid" id="keyframe-grid">
            {keyframes.map((kf) => (
              <div
                key={kf.index}
                id={`keyframe-${kf.index}`}
                className="keyframe-card"
                onClick={() => setSelected(kf)}
                title={`Keyframe ${kf.index} @ ${kf.timestamp_sec.toFixed(2)}s`}
              >
                <div
                  className="keyframe-img"
                  style={{
                    background: kf.image_url
                      ? `url(${kf.image_url}) center/cover no-repeat`
                      : `linear-gradient(135deg, hsl(${250 + kf.index * 8}, 60%, 12%) 0%, hsl(${200 + kf.index * 6}, 50%, 10%) 100%)`,
                  }}
                >
                  {!kf.image_url && '🎬'}
                </div>
                <div className="keyframe-info">
                  <div className="keyframe-time">⏱ {formatSec(kf.timestamp_sec)}</div>
                  <div className="keyframe-delta">SSIM Δ {kf.ssim_delta.toFixed(3)}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Detail modal */}
      {selected && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 200, backdropFilter: 'blur(8px)',
          }}
          onClick={() => setSelected(null)}
        >
          <div
            className="card"
            style={{ maxWidth: 560, width: '90%', padding: '1.5rem' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between" style={{ marginBottom: '1rem' }}>
              <h3>Keyframe #{selected.index}</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setSelected(null)}>✕</button>
            </div>
            {selected.image_url ? (
              <img
                src={selected.image_url}
                alt={`Keyframe ${selected.index}`}
                style={{ width: '100%', borderRadius: 'var(--radius-md)', marginBottom: '1rem' }}
              />
            ) : (
              <div
                style={{
                  width: '100%', aspectRatio: '16/9', background: 'var(--bg-surface)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '3rem', borderRadius: 'var(--radius-md)', marginBottom: '1rem',
                }}
              >🎬</div>
            )}
            <div className="code-block" style={{ lineHeight: 2 }}>
              <div>Timestamp: <span style={{ color: 'var(--text-accent)' }}>{formatSec(selected.timestamp_sec)} ({selected.timestamp_sec.toFixed(3)}s)</span></div>
              <div>Frame #: <span style={{ color: 'var(--text-accent)' }}>{selected.frame_number}</span></div>
              <div>SSIM Δ: <span style={{ color: 'var(--text-accent)' }}>{selected.ssim_delta.toFixed(4)}</span></div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
