import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getKeyframes, getTaskStatus, getAudioUrl, type KeyframeInfo } from '../lib/api'

interface TranscriptSegment {
  start: number
  end: number
  text: string
}

interface JobResult {
  keyframes: KeyframeInfo[]
  transcript: TranscriptSegment[]
}

const fmt = (s: number) => {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

export function Results() {
  const { taskId } = useParams<{ taskId: string }>()
  const [keyframes, setKeyframes] = useState<KeyframeInfo[]>([])
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([])
  const [selected, setSelected] = useState<KeyframeInfo | null>(null)
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hasAudio, setHasAudio] = useState(false)
  const [audioTime, setAudioTime] = useState(0)
  const [slideshow, setSlideshow] = useState(false)
  const [slideshowSpeed, setSlideshowSpeed] = useState(2000)
  const audioRef = useRef<HTMLAudioElement>(null)
  const slideshowRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const thumbnailRefs = useRef<(HTMLDivElement | null)[]>([])

  useEffect(() => {
    if (!taskId) return
    const load = async () => {
      try {
        setLoading(true)
        const kfs = await getKeyframes(taskId)
        setKeyframes(kfs)
        if (kfs.length > 0) {
          setSelected(kfs[0])
          setSelectedIdx(0)
        }
        // Fetch transcript from job result
        try {
          const status = await getTaskStatus(taskId)
          const result = (status as { result?: JobResult }).result
          setTranscript(result?.transcript ?? [])
        } catch { /* transcript optional */ }

        // Check if audio exists
        try {
          const audioUrl = getAudioUrl(taskId)
          const head = await fetch(audioUrl, { method: 'HEAD' })
          setHasAudio(head.ok)
        } catch { setHasAudio(false) }

      } catch (e) {
        setError(String(e))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [taskId])

  // Slideshow controller
  useEffect(() => {
    if (slideshow && keyframes.length > 0) {
      slideshowRef.current = setInterval(() => {
        setSelectedIdx(prev => {
          const next = (prev + 1) % keyframes.length
          setSelected(keyframes[next])
          thumbnailRefs.current[next]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
          return next
        })
      }, slideshowSpeed)
    } else {
      if (slideshowRef.current) clearInterval(slideshowRef.current)
    }
    return () => { if (slideshowRef.current) clearInterval(slideshowRef.current) }
  }, [slideshow, keyframes, slideshowSpeed])

  const selectFrame = (kf: KeyframeInfo, idx: number) => {
    setSelected(kf)
    setSelectedIdx(idx)
    setSlideshow(false)
    // Seek audio to keyframe timestamp
    if (audioRef.current && hasAudio) {
      audioRef.current.currentTime = kf.timestamp_sec
    }
  }

  const prevFrame = () => {
    const idx = Math.max(0, selectedIdx - 1)
    selectFrame(keyframes[idx], idx)
    thumbnailRefs.current[idx]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  const nextFrame = () => {
    const idx = Math.min(keyframes.length - 1, selectedIdx + 1)
    selectFrame(keyframes[idx], idx)
    thumbnailRefs.current[idx]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  // Track audio time for transcript sync
  const onAudioTimeUpdate = () => {
    if (audioRef.current) setAudioTime(audioRef.current.currentTime)
  }

  if (loading) return (
    <div className="page-content animate-fadein">
      <div className="empty-state">
        <div className="spinner" />
        <p>Loading results…</p>
      </div>
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

  // Active transcript segments (within ±30s of selected keyframe)
  const nearTranscript = transcript.filter(s =>
    selected ? (s.start >= selected.timestamp_sec - 3 && s.start <= selected.timestamp_sec + 45) : false
  )
  // Current playing transcript
  const currentSegs = transcript.filter(s => s.start <= audioTime && s.end >= audioTime)

  return (
    <div className="page-content animate-fadein" style={{ padding: '1.5rem' }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
            🎬 Video Results
          </h1>
          <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
            <span className="badge badge-success">{keyframes.length} keyframes</span>
            {transcript.length > 0 && <span className="badge badge-info">{transcript.length} transcript segments</span>}
            {hasAudio && <span className="badge" style={{ background: 'rgba(168,85,247,0.15)', color: '#c084fc', border: '1px solid rgba(168,85,247,0.3)' }}>🎵 Audio available</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Link to={`/chat`} className="btn btn-primary" style={{ fontSize: 13 }}>💬 Chat about this video</Link>
          <Link to="/upload" className="btn btn-ghost" style={{ fontSize: 13 }}>Upload Another</Link>
        </div>
      </div>

      {/* ── Task ID ── */}
      <div className="code-block" style={{ marginBottom: '1.5rem', fontSize: '0.72rem', display: 'inline-block', padding: '0.3rem 0.75rem' }}>
        Task: <span style={{ color: 'var(--text-accent)' }}>{taskId}</span>
      </div>

      {keyframes.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">🎞️</span>
          <h2>No keyframes found</h2>
          <p className="text-muted">The pipeline may still be running — wait a moment and refresh.</p>
          <Link to="/upload" className="btn btn-ghost" style={{ marginTop: '1rem' }}>Back to Upload</Link>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: '1.5rem', alignItems: 'start' }}>

          {/* ── Left: Main viewer + controls ── */}
          <div>
            {/* Main frame viewer */}
            <div style={{
              position: 'relative',
              background: '#0a0f1e',
              borderRadius: 16,
              overflow: 'hidden',
              border: '1px solid rgba(99,102,241,0.3)',
              marginBottom: '1rem',
              boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
            }}>
              {/* Frame image with animation */}
              <div style={{ position: 'relative', aspectRatio: '16/9' }}>
                <img
                  key={selected?.image_url}
                  src={selected?.image_url ?? ''}
                  alt={`Keyframe at ${fmt(selected?.timestamp_sec ?? 0)}`}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'contain',
                    background: '#000',
                    animation: 'fadeIn 0.3s ease',
                  }}
                />
                {/* Timestamp overlay */}
                <div style={{
                  position: 'absolute',
                  bottom: 12,
                  left: 12,
                  background: 'rgba(0,0,0,0.75)',
                  backdropFilter: 'blur(8px)',
                  borderRadius: 8,
                  padding: '4px 12px',
                  fontSize: 14,
                  fontWeight: 700,
                  color: '#818cf8',
                  fontFamily: '"JetBrains Mono", monospace',
                }}>
                  ⏱ {fmt(selected?.timestamp_sec ?? 0)}
                </div>
                {/* Frame index overlay */}
                <div style={{
                  position: 'absolute',
                  top: 12,
                  right: 12,
                  background: 'rgba(99,102,241,0.2)',
                  backdropFilter: 'blur(8px)',
                  borderRadius: 8,
                  padding: '4px 12px',
                  fontSize: 13,
                  fontWeight: 700,
                  color: '#e2e8f0',
                }}>
                  {selectedIdx + 1} / {keyframes.length}
                </div>
                {/* Slideshow badge */}
                {slideshow && (
                  <div style={{
                    position: 'absolute',
                    top: 12,
                    left: 12,
                    background: 'rgba(52,211,153,0.2)',
                    border: '1px solid rgba(52,211,153,0.4)',
                    borderRadius: 8,
                    padding: '4px 10px',
                    fontSize: 12,
                    fontWeight: 700,
                    color: '#34d399',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 5,
                  }}>
                    <span style={{ animation: 'pulse 1s infinite' }}>▶</span> Slideshow
                  </div>
                )}
              </div>
            </div>

            {/* Controls */}
            <div style={{ display: 'flex', gap: 10, marginBottom: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <button
                className="btn btn-secondary"
                onClick={prevFrame}
                disabled={selectedIdx === 0}
                style={{ fontSize: 18, padding: '6px 18px' }}
              >◀ Prev</button>
              <button
                className="btn btn-secondary"
                onClick={nextFrame}
                disabled={selectedIdx === keyframes.length - 1}
                style={{ fontSize: 18, padding: '6px 18px' }}
              >Next ▶</button>
              <button
                className={`btn ${slideshow ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setSlideshow(s => !s)}
                style={{ fontSize: 13 }}
              >
                {slideshow ? '⏸ Stop Slideshow' : '▶ Auto Slideshow'}
              </button>
              {slideshow && (
                <select
                  value={slideshowSpeed}
                  onChange={e => setSlideshowSpeed(Number(e.target.value))}
                  style={{
                    background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155',
                    borderRadius: 8, padding: '6px 10px', fontSize: 12, cursor: 'pointer'
                  }}
                >
                  <option value={1000}>Fast (1s)</option>
                  <option value={2000}>Normal (2s)</option>
                  <option value={4000}>Slow (4s)</option>
                </select>
              )}
            </div>

            {/* Audio player */}
            {hasAudio && taskId && (
              <div style={{
                background: 'linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.1))',
                border: '1px solid rgba(99,102,241,0.25)',
                borderRadius: 14,
                padding: '14px 18px',
                marginBottom: '1rem',
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#818cf8', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                  🎵 Extracted Audio
                  {currentSegs.length > 0 && (
                    <span style={{ fontSize: 11, fontWeight: 400, color: '#64748b' }}>
                      — {currentSegs[0].text.slice(0, 60)}…
                    </span>
                  )}
                </div>
                <audio
                  ref={audioRef}
                  controls
                  onTimeUpdate={onAudioTimeUpdate}
                  style={{ width: '100%', borderRadius: 8 }}
                  src={getAudioUrl(taskId)}
                />
                <div style={{ fontSize: 11, color: '#475569', marginTop: 6 }}>
                  Click a keyframe to seek audio to that timestamp
                </div>
              </div>
            )}

            {/* Keyframe strip (thumbnails) */}
            <h3 style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 2, marginBottom: '0.75rem' }}>
              Keyframe Gallery
            </h3>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {keyframes.map((kf, idx) => (
                <div
                  key={kf.index}
                  id={`kf-${kf.index}`}
                  ref={el => { thumbnailRefs.current[idx] = el }}
                  onClick={() => selectFrame(kf, idx)}
                  style={{
                    width: 120,
                    cursor: 'pointer',
                    borderRadius: 10,
                    overflow: 'hidden',
                    border: selectedIdx === idx
                      ? '2px solid #6366f1'
                      : '2px solid rgba(255,255,255,0.05)',
                    transition: 'all 0.2s ease',
                    transform: selectedIdx === idx ? 'scale(1.06)' : 'scale(1)',
                    boxShadow: selectedIdx === idx ? '0 0 20px rgba(99,102,241,0.4)' : 'none',
                    flexShrink: 0,
                  }}
                >
                  <div style={{ aspectRatio: '16/9', background: '#0a0f1e', position: 'relative' }}>
                    <img
                      src={kf.image_url}
                      alt={`Frame ${idx}`}
                      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                      loading="lazy"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                    {/* Audio sync indicator */}
                    {hasAudio && audioTime >= kf.timestamp_sec && audioTime < (keyframes[idx + 1]?.timestamp_sec ?? Infinity) && (
                      <div style={{
                        position: 'absolute', bottom: 2, left: 2,
                        width: 6, height: 6, borderRadius: '50%',
                        background: '#34d399', boxShadow: '0 0 8px #34d399',
                        animation: 'pulse 1s infinite',
                      }} />
                    )}
                  </div>
                  <div style={{
                    padding: '3px 6px',
                    fontSize: 10,
                    fontWeight: 600,
                    color: selectedIdx === idx ? '#818cf8' : '#64748b',
                    background: '#0f172a',
                    textAlign: 'center',
                  }}>
                    {fmt(kf.timestamp_sec)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Right: Detail panel ── */}
          <div style={{ position: 'sticky', top: '1rem' }}>
            {/* Frame info */}
            <div className="card" style={{ marginBottom: '1rem', background: 'rgba(15,23,42,0.8)' }}>
              <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-accent)', marginBottom: 10 }}>
                📍 Frame #{selected?.index ?? 0} — {fmt(selected?.timestamp_sec ?? 0)}
              </h3>
              {selected?.ssim_delta && selected.ssim_delta > 0 ? (
                <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 11, color: '#64748b' }}>SSIM delta:</span>
                  <span style={{
                    fontSize: 11, fontWeight: 700,
                    color: selected.ssim_delta > 0.3 ? '#f87171' : selected.ssim_delta > 0.1 ? '#f59e0b' : '#34d399'
                  }}>
                    {selected.ssim_delta.toFixed(4)}
                  </span>
                </div>
              ) : null}
              {/* Progress bar through video */}
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 11, color: '#475569', marginBottom: 4 }}>Timeline position</div>
                <div style={{ height: 4, background: '#1e293b', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%',
                    width: `${keyframes.length > 1 ? (selectedIdx / (keyframes.length - 1)) * 100 : 0}%`,
                    background: 'linear-gradient(90deg,#6366f1,#8b5cf6)',
                    transition: 'width 0.3s ease',
                    borderRadius: 4,
                  }} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#475569', marginTop: 3 }}>
                  <span>{fmt(keyframes[0]?.timestamp_sec ?? 0)}</span>
                  <span>{fmt(keyframes[keyframes.length - 1]?.timestamp_sec ?? 0)}</span>
                </div>
              </div>
            </div>

            {/* Transcript near this frame */}
            {transcript.length > 0 && (
              <div className="card" style={{ background: 'rgba(15,23,42,0.8)' }}>
                <h3 style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: 'var(--text-primary)' }}>
                  📝 Transcript
                  <span style={{ fontSize: 11, color: '#64748b', fontWeight: 400, marginLeft: 6 }}>
                    near this frame
                  </span>
                </h3>
                <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                  {nearTranscript.length > 0 ? nearTranscript.map((s, i) => {
                    const isActive = audioTime >= s.start && audioTime <= s.end
                    return (
                      <div
                        key={i}
                        onClick={() => { if (audioRef.current) audioRef.current.currentTime = s.start }}
                        style={{
                          padding: '6px 8px',
                          marginBottom: 4,
                          borderRadius: 8,
                          background: isActive ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.03)',
                          border: isActive ? '1px solid rgba(99,102,241,0.4)' : '1px solid transparent',
                          cursor: hasAudio ? 'pointer' : 'default',
                          transition: 'all 0.2s ease',
                          fontSize: 12,
                          lineHeight: 1.5,
                        }}
                      >
                        <span style={{ color: '#818cf8', fontWeight: 700, fontFamily: 'monospace', marginRight: 8 }}>
                          {fmt(s.start)}
                        </span>
                        <span style={{ color: isActive ? '#e2e8f0' : '#94a3b8' }}>{s.text}</span>
                      </div>
                    )
                  }) : (
                    <p className="text-sm text-muted">No transcript near this frame.</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Actions ── */}
      <div className="flex gap-3" style={{ marginTop: '2rem', flexWrap: 'wrap' }}>
        <Link to="/chat" className="btn btn-primary" id="results-chat-btn">💬 Chat about this video</Link>
        <a href="/query" className="btn btn-secondary" id="results-query-btn">🔍 Ask a Question</a>
        <Link to="/upload" className="btn btn-ghost" id="results-upload-btn">Upload Another</Link>
      </div>

      {/* Fade in keyframe animation */}
      <style>{`
        @keyframes fadeIn { from { opacity: 0; transform: scale(0.98); } to { opacity: 1; transform: scale(1); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
      `}</style>
    </div>
  )
}
