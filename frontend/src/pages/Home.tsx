import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useHealth } from '../hooks/useHealth'
import { getStats, listVideos, type StatsResponse, type VideoListItem } from '../lib/api'

interface StatCardProps {
  value: string | number
  label: string
  icon: string
  loading?: boolean
  accent?: string
}

function StatCard({ value, label, icon, loading, accent }: StatCardProps) {
  return (
    <div className="stat-card animate-slidein" style={accent ? { borderColor: accent } : {}}>
      <div style={{ fontSize: '1.4rem', marginBottom: '6px' }}>{icon}</div>
      <div className="stat-value" style={accent ? { color: accent } : {}}>
        {loading ? <span className="spinner" style={{ width: 22, height: 22 }} /> : value}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

const STATUS_COLOR: Record<string, string> = {
  done:       '#00FF88',
  processing: '#00F0FF',
  queued:     '#FFCC00',
  failed:     '#FF0055',
}

export function Home() {
  const { health, loading: healthLoading } = useHealth()
  const [stats, setStats]   = useState<StatsResponse | null>(null)
  const [videos, setVideos] = useState<VideoListItem[]>([])
  const [statsLoading, setStatsLoading] = useState(true)

  const loadAll = async () => {
    try {
      setStatsLoading(true)
      const [s, vids] = await Promise.all([getStats(), listVideos().catch(() => [])])
      setStats(s)
      setVideos(vids)
    } catch {
      // non-fatal
    } finally {
      setStatsLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
    const id = setInterval(loadAll, 30_000)
    return () => clearInterval(id)
  }, [])

  const lastTaskId = localStorage.getItem('videorag_last_task_id')

  return (
    <div className="page-content animate-fadein">
      <div className="glow-bg" aria-hidden />
      <div className="glow-bg-2" aria-hidden />

      {/* ── Hero ── */}
      <div style={{ marginBottom: '2rem', position: 'relative', zIndex: 1 }}>
        <h1 className="page-title" style={{ fontSize: '2rem', fontWeight: 900 }}>
          🎬 Semantic Video Synthesizer
        </h1>
        <p className="page-subtitle" style={{ maxWidth: 560, marginTop: 8 }}>
          Upload a lecture or talk — the pipeline extracts keyframes via SSIM, transcribes audio,
          structures it with an LLM, and indexes everything into a local FAISS store for
          natural-language Q&A.
        </p>
      </div>

      {/* ── Quick Actions ── */}
      <div className="flex gap-3" style={{ marginBottom: '2rem', flexWrap: 'wrap', position: 'relative', zIndex: 1 }}>
        <Link to="/upload" className="btn btn-primary" id="action-upload">📤 Upload a Video</Link>
        <Link to="/chat"   className="btn btn-secondary" id="action-chat">💬 Chat with AI</Link>
        <Link to="/query"  className="btn btn-secondary" id="action-query">🔍 Ask a Question</Link>
        {lastTaskId && (
          <Link to={`/results/${lastTaskId}`} className="btn btn-ghost" id="action-last-results">
            🎞️ Last Results
          </Link>
        )}
      </div>

      {/* ── System Status ── */}
      <div className="card" style={{ marginBottom: '1.5rem', position: 'relative', zIndex: 1 }}>
        <div className="flex items-center justify-between" style={{ marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 700, margin: 0 }}>⚡ System Status</h2>
          {healthLoading ? (
            <div className="spinner" />
          ) : (
            <span className={`badge ${health?.status === 'ok' ? 'badge-success' : 'badge-error'}`}>
              {health?.status === 'ok' ? '● Live' : '● Offline'}
            </span>
          )}
        </div>
        <div className="grid-3">
          {[
            { label: 'FastAPI Backend', icon: '🚀', ok: !!health },
            { label: 'Redis',          icon: '🔴', ok: !!health?.redis },
            { label: 'Celery Worker',  icon: '⚙️', ok: !!health?.celery },
          ].map((svc) => (
            <div
              key={svc.label}
              className="card-glass"
              id={`status-${svc.label.toLowerCase().replace(/\s+/g, '-')}`}
              style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', gap: '12px' }}
            >
              <span style={{ fontSize: '1.4rem' }}>{svc.icon}</span>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-pure)' }}>{svc.label}</div>
                <div style={{ fontSize: '0.75rem', color: svc.ok ? '#34d399' : '#f87171', fontWeight: 700, marginTop: 2 }}>
                  {healthLoading ? 'Checking…' : svc.ok ? '● Healthy' : '● Offline'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Live Stats ── */}
      <div className="stats-grid" style={{ marginBottom: '1.5rem', position: 'relative', zIndex: 1 }}>
        <StatCard value={stats?.videos_indexed ?? 0}    label="Videos Indexed"      icon="🎬" loading={statsLoading} accent="var(--accent-cyan)" />
        <StatCard value={stats?.keyframes_extracted ?? 0} label="Keyframes Extracted" icon="🎞️" loading={statsLoading} />
        <StatCard value={stats?.jobs_in_progress ?? 0}  label="Jobs In Progress"     icon="⚙️" loading={statsLoading}
          accent={stats?.jobs_in_progress ? '#fbbf24' : undefined} />
        <StatCard value="FAISS + Ollama" label="Local AI Stack"   icon="🧠" />
      </div>

      {/* ── Recent Videos ── */}
      {videos.length > 0 && (
        <div className="card" style={{ marginBottom: '1.5rem', position: 'relative', zIndex: 1 }}>
          <div className="flex items-center justify-between" style={{ marginBottom: '1rem' }}>
            <h2 style={{ fontSize: '0.95rem', fontWeight: 700, margin: 0 }}>📂 Indexed Videos</h2>
            <Link to="/keyframes" className="btn btn-ghost" style={{ fontSize: '0.78rem', padding: '5px 12px' }}>
              Browse All
            </Link>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {videos.slice(0, 6).map((v) => (
              <Link
                key={v.job_id}
                to={`/results/${v.job_id}`}
                style={{ textDecoration: 'none' }}
              >
                <div
                  className="card-glass"
                  style={{ padding: '11px 16px', display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }}
                >
                  <span style={{ fontSize: '1.1rem' }}>🎞️</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="truncate" style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--text-pure)' }}>
                      {v.filename}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>
                      {v.keyframe_count} keyframes
                    </div>
                  </div>
                  <span style={{ fontSize: '0.72rem', fontWeight: 700, color: STATUS_COLOR[v.status] ?? '#8A8A9E' }}>
                    {v.status.toUpperCase()}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* ── Pipeline Summary ── */}
      <div className="card" style={{ borderColor: 'rgba(112,0,255,0.2)', position: 'relative', zIndex: 1 }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: '1rem', color: 'var(--text-accent)' }}>
          🏗️ How the Pipeline Works
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            ['1', 'SSIM Keyframe Extraction',       'Detects scene changes without ML — fast, deterministic.'],
            ['2', 'Audio Extraction (ffmpeg)',       'Strips the audio track for transcription.'],
            ['3', 'VLM + Whisper (parallel)',        'OCR reads slide text; Whisper transcribes speech.'],
            ['4', 'LLM Transcript Structuring',     'Ollama converts raw speech → topic/summary/key-terms JSON.'],
            ['5', 'FAISS RAG Indexing',              'All chunks embedded with nomic-embed-text and stored locally.'],
          ].map(([n, title, desc]) => (
            <div key={n} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                background: 'rgba(0,240,255,0.1)', border: '1px solid rgba(0,240,255,0.2)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '0.75rem', fontWeight: 800, color: 'var(--accent-cyan)',
              }}>{n}</div>
              <div>
                <div style={{ fontWeight: 700, fontSize: '0.875rem', color: 'var(--text-pure)', marginBottom: 2 }}>{title}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
