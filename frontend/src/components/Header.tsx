interface HeaderProps {
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
}

export function Header({ sidebarCollapsed, onToggleSidebar }: HeaderProps) {
  return (
    <header className="header" role="banner">
      {sidebarCollapsed && (
        <>
          <div className="header-logo">
            <div className="logo-icon">🎬</div>
            <span style={{
              background: 'linear-gradient(135deg, #f0f0ff 0%, #a78bfa 100%)',
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
      >
        {sidebarCollapsed ? '☰' : '◀'}
      </button>

      <div className="header-spacer" />

      <span
        className="badge badge-purple"
        id="version-badge"
        title="Current build version"
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
      >
        ⭐
      </a>
    </header>
  )
}
