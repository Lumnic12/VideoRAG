import { useState, useEffect } from 'react'
import { useHealth } from '../hooks/useHealth'
import { getStats, type StatsResponse } from '../lib/api'

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
      <div style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>{icon}</div>
      <div className="stat-value" style={accent ? { color: accent } : {}}>
        {loading ? <span className="spinner" style={{ width: 24, height: 24 }} /> : value}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

export function Home() {
  const { health, loading: healthLoading } = useHealth()
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)

  const loadStats = async () => {
    try {
      setStatsLoading(true)
      const s = await getStats()
      setStats(s)
    } catch {
      // stats failure is non-fatal
    } finally {
      setStatsLoading(false)
    }
  }

  useEffect(() => {
    loadStats()
    const interval = setInterval(loadStats, 30_000)
    return () => clearInterval(interval)
  }, [])

  const lastTaskId = localStorage.getItem('videorag_last_task_id')

  return (
    <div className="page-content animate-fadein">
      <div className="glow-bg" aria-hidden />
      <div className="glow-bg-2" aria-hidden />

      <div className="page-header">
        <h1 className="page-title">VideoRAG Platform</h1>
        <p className="page-subtitle">
          AI-powered video understanding — extract keyframes, index transcripts, and query your video library with natural language.
        </p>
      </div>

      {/* System Status */}
      <div className="card" style={{ marginBottom: '2rem' }}>
        <div className="flex items-center justify-between" style={{ marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '1rem', fontWeight: 700, margin: 0 }}>System Status</h2>
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
            { label: 'FastAPI', icon: '🚀', ok: !!health },
            { label: 'Redis', icon: '🔴', ok: !!health?.redis },
            { label: 'Celery', icon: '⚙️', ok: !!health?.celery },
          ].map((svc) => (
            <div
              key={svc.label}
              className="card-glass"
              id={`status-${svc.label.toLowerCase()}`}
              style={{ padding: '1rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}
            >
              <span style={{ fontSize: '1.5rem' }}>{svc.icon}</span>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>{svc.label}</div>
                <div style={{ fontSize: '0.75rem', color: svc.ok ? '#34d399' : '#f87171', fontWeight: 600 }}>
                  {healthLoading ? 'Checking…' : svc.ok ? 'Healthy' : 'Offline'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Live Stats */}
      <div className="stats-grid" style={{ marginBottom: '2rem' }}>
        <StatCard
          value={stats?.videos_indexed ?? 0}
          label="Videos Indexed"
          icon="🎬"
          loading={statsLoading}
          accent="var(--accent-primary)"
        />
        <StatCard
          value={stats?.keyframes_extracted ?? 0}
          label="Keyframes Extracted"
          icon="🎞️"
          loading={statsLoading}
        />
        <StatCard
          value={stats?.jobs_in_progress ?? 0}
          label="Jobs In Progress"
          icon="⚙️"
          loading={statsLoading}
          accent={stats?.jobs_in_progress ? '#fbbf24' : undefined}
        />
        <StatCard
          value="FAISS"
          label="Vector Store"
          icon="⚡"
        />
      </div>

      {/* Quick Actions */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '1rem' }}>Quick Actions</h2>
        <div className="flex gap-3" style={{ flexWrap: 'wrap' }}>
          <a href="/upload" className="btn btn-primary" id="action-upload">📤 Upload a Video</a>
          <a href="/query"  className="btn btn-secondary" id="action-query">🔍 Ask a Question</a>
          {lastTaskId && (
            <a href={`/results/${lastTaskId}`} className="btn btn-ghost" id="action-last-results">
              🎞️ Last Results
            </a>
          )}
          <a href="/keyframes" className="btn btn-ghost" id="action-keyframes">Browse Keyframes</a>
        </div>
      </div>

      {/* Architecture Note */}
      <div className="card" style={{ borderColor: 'rgba(124,58,237,0.25)' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: '0.75rem', color: 'var(--text-accent)' }}>
          🏗️ Architecture (ADR Summary)
        </h2>
        <div className="code-block">
          {`ADR-001: Python SSIM pipeline (C++ in Phase 4)\nADR-002: FAISS locally (Pinecone for production)\nPhase 1 ✅  Phase 2 🔄  Phase 3 ○  Phase 4 ○`}
        </div>
      </div>
    </div>
  )
}
