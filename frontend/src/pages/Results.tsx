import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getKeyframes, getTaskStatus, type KeyframeInfo } from '../lib/api'

interface TranscriptSegment {
  start: number
  end: number
  text: string
}

interface JobResult {
  keyframes: KeyframeInfo[]
  transcript: TranscriptSegment[]
}

export function Results() {
  const { taskId } = useParams<{ taskId: string }>()
  const [keyframes, setKeyframes] = useState<KeyframeInfo[]>([])
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([])
  const [selected, setSelected] = useState<KeyframeInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) return
    const load = async () => {
      try {
        setLoading(true)
        // Fetch keyframes
        const kfs = await getKeyframes(taskId)
        setKeyframes(kfs)
        if (kfs.length > 0) setSelected(kfs[0])

        // Fetch full job result for transcript
        const status = await getTaskStatus(taskId)
        const result = (status as { result?: JobResult }).result
        setTranscript(result?.transcript ?? [])
      } catch (e) {
        setError(String(e))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [taskId])

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  if (loading) return (
    <div className="page-content animate-fadein">
      <div className="empty-state"><div className="spinner" /><p>Loading results…</p></div>
    </div>
  )

  if (error) return (
    <div className="page-content animate-fadein">
      <div className="empty-state">
        <span className="empty-icon">⚠️</span>
        <h2>Failed to load results</h2>
        <p className="text-sm text-muted">{error}</p>
        <Link to="/upload" className="btn btn-secondary" style={{ marginTop: '1rem' }}>Back to Upload</Link>
      </div>
    </div>
  )

  return (
    <div className="page-content animate-fadein">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center gap-3" style={{ flexWrap: 'wrap' }}>
          <h1 className="page-title" style={{ marginBottom: 0 }}>Results</h1>
          <span className="badge badge-success">{keyframes.length} keyframes</span>
          {transcript.length > 0 && <span className="badge badge-info">{transcript.length} transcript segments</span>}
        </div>
        <div className="code-block" style={{ marginTop: '0.5rem', fontSize: '0.75rem', display: 'inline-block', padding: '0.3rem 0.75rem' }}>
          Task: <span style={{ color: 'var(--text-accent)' }}>{taskId}</span>
        </div>
      </div>

      {keyframes.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">🎞️</span>
          <h2>No keyframes found</h2>
          <p className="text-muted">The pipeline may still be running — wait a moment and refresh.</p>
          <Link to="/upload" className="btn btn-ghost" style={{ marginTop: '1rem' }}>Back to Upload</Link>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: selected ? '1fr 340px' : '1fr', gap: '1.5rem', alignItems: 'start' }}>

          {/* ── Keyframe grid ── */}
          <div>
            <h2 style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: '1rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 2 }}>
              Keyframe Gallery
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.75rem' }}>
              {keyframes.map((kf) => (
                <div
                  key={kf.index}
                  id={`kf-${kf.index}`}
                  className={`card-glass${selected?.index === kf.index ? ' selected' : ''}`}
                  style={{
                    cursor: 'pointer',
                    overflow: 'hidden',
                    border: selected?.index === kf.index ? '2px solid var(--accent-primary)' : '1px solid rgba(255,255,255,0.07)',
                    transition: 'border 0.2s ease, transform 0.2s ease',
                    transform: selected?.index === kf.index ? 'scale(1.02)' : 'scale(1)',
                  }}
                  onClick={() => setSelected(kf)}
                >
                  <div style={{ aspectRatio: '16/9', background: 'rgba(0,0,0,0.4)', position: 'relative' }}>
                    <img
                      src={`http://localhost:8000${kf.image_url}`}
                      alt={`Keyframe at ${formatTime(kf.timestamp_sec)}`}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      loading="lazy"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none'
                      }}
                    />
                    <div style={{
                      position: 'absolute', bottom: 0, left: 0, right: 0,
                      background: 'linear-gradient(transparent, rgba(0,0,0,0.8))',
                      padding: '0.5rem',
                      fontSize: '0.7rem',
                      fontWeight: 600,
                      color: 'var(--text-accent)',
                    }}>
                      {formatTime(kf.timestamp_sec)}
                    </div>
                  </div>
                  <div style={{ padding: '0.5rem 0.75rem' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      Keyframe #{kf.index}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Selected keyframe detail + transcript ── */}
          {selected && (
            <div style={{ position: 'sticky', top: '1rem' }}>
              <div className="card" style={{ marginBottom: '1rem' }}>
                <h3 style={{ fontSize: '0.85rem', fontWeight: 700, marginBottom: '0.75rem', color: 'var(--text-accent)' }}>
                  Frame #{selected.index} — {formatTime(selected.timestamp_sec)}
                </h3>
                <img
                  src={`http://localhost:8000${selected.image_url}`}
                  alt={`Keyframe ${selected.index}`}
                  style={{ width: '100%', borderRadius: 'var(--radius-sm)', marginBottom: '0.75rem' }}
                />
                {selected.ssim_delta > 0 && (
                  <div className="text-sm text-muted">SSIM delta: <strong>{selected.ssim_delta.toFixed(4)}</strong></div>
                )}
              </div>

              {/* Transcript near this keyframe */}
              {transcript.length > 0 && (
                <div className="card">
                  <h3 style={{ fontSize: '0.85rem', fontWeight: 700, marginBottom: '0.75rem' }}>Transcript</h3>
                  <div style={{ maxHeight: 280, overflowY: 'auto' }}>
                    {transcript
                      .filter(s => s.start >= selected.timestamp_sec - 5 && s.start <= selected.timestamp_sec + 30)
                      .map((s, i) => (
                        <div key={i} style={{
                          padding: '0.4rem 0.6rem', marginBottom: '0.3rem',
                          background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-sm)',
                          fontSize: '0.8rem',
                        }}>
                          <span style={{ color: 'var(--text-accent)', fontWeight: 600, marginRight: '0.5rem' }}>
                            {formatTime(s.start)}
                          </span>
                          {s.text}
                        </div>
                      ))
                    }
                    {transcript.filter(s => s.start >= selected.timestamp_sec - 5 && s.start <= selected.timestamp_sec + 30).length === 0 && (
                      <p className="text-sm text-muted">No transcript segments near this timestamp.</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Actions ── */}
      <div className="flex gap-3" style={{ marginTop: '2rem', flexWrap: 'wrap' }}>
        <a href="/query" className="btn btn-primary" id="results-query-btn">🔍 Ask a Question</a>
        <Link to={`/keyframes?task=${taskId}`} className="btn btn-secondary" id="results-keyframes-btn">🎞️ Full Gallery</Link>
        <Link to="/upload" className="btn btn-ghost" id="results-upload-btn">Upload Another</Link>
      </div>
    </div>
  )
}
