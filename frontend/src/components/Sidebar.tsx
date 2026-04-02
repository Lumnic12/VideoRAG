import { NavLink } from 'react-router-dom'
import { useHealth } from '../hooks/useHealth'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

const NAV_ITEMS = [
  { to: '/', icon: '⚡', label: 'Dashboard' },
  { to: '/upload', icon: '📤', label: 'Upload Video' },
  { to: '/query', icon: '🔍', label: 'Ask VideoRAG' },
  { to: '/keyframes', icon: '🎞️', label: 'Keyframes' },
]

const PHASE_ITEMS = [
  { label: 'Phase 0: Skeleton ✓', done: true },
  { label: 'Phase 1: Ingestion', done: false },
  { label: 'Phase 2: RAG Engine', done: false },
  { label: 'Phase 3: SSIM Polish', done: false },
]

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { health } = useHealth()

  return (
    <aside className={`sidebar${collapsed ? ' collapsed' : ''}`} id="sidebar">
      {/* Logo */}
      <div className="sidebar-header">
        <div className="sidebar-logo-icon">🎬</div>
        <span className="sidebar-logo">VideoRAG</span>
        <button
          id="sidebar-close-btn"
          className="toggle-btn"
          onClick={onToggle}
          title="Collapse sidebar"
          style={{ marginLeft: 'auto' }}
          aria-label="Close sidebar"
        >
          ✕
        </button>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav" aria-label="Main navigation">
        <span className="nav-section-label">Navigation</span>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            id={`nav-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            end={item.to === '/'}
          >
            <span className="nav-icon">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}

        <div className="divider" style={{ margin: '0.75rem 0' }} />

        <span className="nav-section-label">Phases</span>
        {PHASE_ITEMS.map((p) => (
          <div
            key={p.label}
            className="nav-item"
            style={{ cursor: 'default', opacity: p.done ? 1 : 0.5 }}
          >
            <span className="nav-icon">{p.done ? '✅' : '○'}</span>
            <span style={{ fontSize: '0.78rem' }}>{p.label}</span>
          </div>
        ))}
      </nav>

      {/* Footer: health status */}
      <div className="sidebar-footer">
        <div className="card-glass" style={{ padding: '0.75rem 1rem' }}>
          <div className="flex items-center gap-2" style={{ marginBottom: '0.5rem' }}>
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: health?.status === 'ok' ? '#34d399' : '#f87171',
                boxShadow: health?.status === 'ok' ? '0 0 6px #34d399' : '0 0 6px #f87171',
              }}
            />
            <span className="text-xs" style={{ color: health?.status === 'ok' ? '#34d399' : '#f87171', fontWeight: 600 }}>
              {health?.status === 'ok' ? 'All Systems OK' : 'Backend Offline'}
            </span>
          </div>
          <div className="flex gap-2 text-xs text-muted">
            <span>Redis: {health?.redis ? '✓' : '✗'}</span>
            <span>Celery: {health?.celery ? '✓' : '✗'}</span>
          </div>
        </div>
      </div>
    </aside>
  )
}
