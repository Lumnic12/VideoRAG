interface HeaderProps {
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  lightTheme: boolean
  onToggleLightTheme: () => void
}

export function Header({ 
  sidebarCollapsed, 
  onToggleSidebar,
  lightTheme,
  onToggleLightTheme
}: HeaderProps) {
  return (
    <header className="header" role="banner" style={{ background: 'var(--bg-card)', borderBottom: '1px solid var(--border-subtle)', backdropFilter: 'blur(10px)' }}>
      {sidebarCollapsed && (
        <>
          <div className="header-logo">
            <div className="logo-icon">🎬</div>
            <span style={{
              background: 'var(--gradient-neon)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              VideoRAG
            </span>
          </div>
        </>
      )}

      <button
        id="sidebar-toggle-btn"
        className="toggle-btn"
        onClick={onToggleSidebar}
        title={sidebarCollapsed ? 'Open sidebar' : 'Close sidebar'}
        aria-label="Toggle sidebar"
        style={{ background: 'transparent', color: 'var(--text-main)', border: 'none', cursor: 'pointer', padding: '8px' }}
      >
        {sidebarCollapsed ? '☰' : '◀'}
      </button>

      <div className="header-spacer" style={{ flex: 1 }} />

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginRight: 16 }}>
        <button
          className="btn btn-secondary"
          style={{
            background: lightTheme ? 'rgba(0,0,0,0.05)' : 'transparent',
            borderColor: lightTheme ? 'var(--border-light)' : 'var(--border-light)',
            color: 'var(--text-main)',
            padding: '4px 12px',
            fontSize: 12
          }}
          onClick={onToggleLightTheme}
          title="Toggle Light Theme"
        >
          {lightTheme ? '🌙 Dark' : '☀️ Light'}
        </button>
      </div>

      <span
        className="badge"
        id="version-badge"
        title="Current build version"
        style={{ background: 'rgba(0, 240, 255, 0.1)', color: 'var(--accent-cyan)', border: '1px solid rgba(0, 240, 255, 0.2)' }}
      >
        v0.1.0-alpha
      </span>

      <a
        href="https://github.com"
        id="github-link"
        className="btn btn-ghost btn-icon"
        title="GitHub"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="GitHub repository"
        style={{ color: 'var(--text-main)', textDecoration: 'none', marginLeft: 16 }}
      >
        ⭐
      </a>
    </header>
  )
}
