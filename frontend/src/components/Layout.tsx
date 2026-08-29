import { type ReactNode, useState } from 'react'
import { useLocation, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useTheme } from '../hooks/useTheme'

interface Props {
  children:        ReactNode
  sidebar?:        ReactNode
  headerExtra?:    ReactNode
}

export function Layout({ children, sidebar, headerExtra }: Props) {
  const { user } = useAuth()
  const { toggle } = useTheme()
  const location = useLocation()
  const [logoutConfirm, setLogoutConfirm] = useState(false)

  const pageSubs: Record<string, string> = {
    '/review':    'Batch Review',
    '/view':      'View',
    '/shared':    'Shared Expenses',
    '/recurring': 'Recurring Transactions',
  }
  const logoSub = pageSubs[location.pathname] ?? 'Finance Manager'

  const navLinks = [
    { to: '/review',    label: 'Review' },
    { to: '/view',      label: 'View' },
    { to: '/shared',    label: 'Shared' },
    { to: '/recurring', label: 'Recurring' },
  ]

  const dateStr = new Date().toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })

  return (
    <div className="page-layout">
      {/* Header */}
      <header className="site-header">
        <div className="logo">
          <div className="logo-mark">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <polyline points="2,13 6,8 10,10 16,4" stroke="#0a0a10" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="16" cy="4" r="2" fill="#0a0a10"/>
            </svg>
          </div>
          <div>
            <div className="logo-text">ExpTrack</div>
            <div className="logo-sub">{logoSub}</div>
          </div>
        </div>

        <div className="header-right">
          <nav className="header-nav">
            {navLinks.map(l => (
              <Link
                key={l.to}
                to={l.to}
                className={`nav-link${location.pathname === l.to ? ' active' : ''}`}
              >
                {l.label}
              </Link>
            ))}
          </nav>
          {user && (
            <span className="user-chip">{user.username}</span>
          )}
          <span className="header-date">{dateStr}</span>
          {headerExtra}
          <button className="theme-toggle" onClick={toggle} title="Toggle theme" aria-label="Toggle light/dark theme">
            <span className="toggle-icon">🌙</span>
            <span className="toggle-track"><span className="toggle-thumb" /></span>
            <span className="toggle-icon">☀️</span>
          </button>
          <button className="nav-link" onClick={() => setLogoutConfirm(true)}>
            Logout
          </button>
        </div>
      </header>

      {/* Content */}
      <div className="main-content">
        {sidebar ? (
          <div className="content-layout">
            <aside className="sidebar">{sidebar}</aside>
            <div className="main-panel">{children}</div>
          </div>
        ) : (
          <div style={{ paddingTop: 16 }}>{children}</div>
        )}
      </div>

      {/* Logout confirm */}
      {logoutConfirm && (
        <div className="modal-overlay" onClick={() => setLogoutConfirm(false)}>
          <div className="modal-box" style={{ width: 320 }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">Confirm Logout</div>
            <div className="modal-body" style={{ padding: '16px 18px', fontSize: 14 }}>
              Are you sure you want to log out?
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setLogoutConfirm(false)}>
                Cancel
              </button>
              <a href="/logout" className="btn btn-danger">Logout</a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
