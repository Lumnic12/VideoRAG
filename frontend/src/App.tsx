import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { Header } from './components/Header'
import { Home } from './pages/Home'
import { Upload } from './pages/Upload'
import { Query } from './pages/Query'
import { Keyframes } from './pages/Keyframes'
import { Results } from './pages/Results'
import { Chat } from './pages/Chat'

export default function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [lightTheme, setLightTheme] = useState(false)

  useEffect(() => {
    if (lightTheme) document.body.classList.add('light-theme')
    else document.body.classList.remove('light-theme')
  }, [lightTheme])

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed((c) => !c)}
        />

        <div className={`main-content${sidebarCollapsed ? ' expanded' : ''}`}>
          <Header
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed((c) => !c)}
            lightTheme={lightTheme}
            onToggleLightTheme={() => setLightTheme(!lightTheme)}
          />

          <main style={{ flex: 1, position: 'relative' }}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/upload" element={<Upload />} />
              <Route path="/query" element={<Query />} />
              <Route path="/keyframes" element={<Keyframes />} />
              <Route path="/results/:taskId" element={<Results />} />
              <Route path="*" element={
                <div className="page-content animate-fadein">
                  <div className="empty-state">
                    <span className="empty-icon">404</span>
                    <h2>Page not found</h2>
                    <a href="/" className="btn btn-primary">Go Home</a>
                  </div>
                </div>
              } />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
