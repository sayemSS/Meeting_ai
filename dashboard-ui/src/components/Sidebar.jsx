import React from 'react'
import { NavLink } from 'react-router-dom'
import { useHealth } from '../hooks/useHealth'

const NAV = [
  { to: '/new',      label: 'New Meeting', icon: <IconPlus /> },
  { to: '/live',     label: 'Live',        icon: <IconLive /> },
  { to: '/meetings', label: 'Meetings',    icon: <IconCalendar /> },
]

export default function Sidebar({ liveCounts = 0 }) {
  const health = useHealth()

  return (
    <aside style={{
      width: 220, minWidth: 220,
      background: 'var(--surface)',
      borderRight: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column',
      height: '100vh', position: 'sticky', top: 0,
    }}>
      {/* Logo */}
      <div style={{
        padding: '20px 20px 16px',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <div style={{
          width: 32, height: 32, background: 'var(--accent)',
          borderRadius: 8, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontSize: 16,
        }}>🎙</div>
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, letterSpacing: -0.3 }}>MeetPilot</div>
          <div style={{ fontSize: 10, color: 'var(--muted)', letterSpacing: 0.5, textTransform: 'uppercase' }}>
            AI Assistant
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ padding: '12px 10px', flex: 1 }}>
        {NAV.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => ({
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '9px 12px', borderRadius: 8,
              color: isActive ? 'var(--accent)' : 'var(--muted)',
              background: isActive ? 'var(--accent-dim)' : 'transparent',
              fontSize: 13.5, fontWeight: 500, marginBottom: 2,
              textDecoration: 'none', transition: 'background .15s, color .15s',
            })}
          >
            {icon}
            <span style={{ flex: 1 }}>{label}</span>
            {to === '/live' && liveCounts > 0 && (
              <span style={{
                background: 'var(--accent)', color: '#fff',
                fontSize: 10, fontWeight: 700, padding: '2px 6px',
                borderRadius: 10, fontFamily: 'var(--mono)',
              }}>{liveCounts}</span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Health footer */}
      <div style={{
        padding: '12px 16px', borderTop: '1px solid var(--border)',
        fontSize: 11, color: 'var(--muted2)',
        display: 'flex', alignItems: 'center', gap: 7,
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
          background: health.ok ? 'var(--success)' : 'var(--danger)',
          animation: health.ok ? 'mp-pulse 2s infinite' : 'none',
        }} />
        {health.ok ? `${health.active_sessions} active session${health.active_sessions !== 1 ? 's' : ''}` : 'Backend offline'}
      </div>
    </aside>
  )
}

function IconPlus() {
  return <svg width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
}
function IconLive() {
  return <svg width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M6.3 6.3a8 8 0 0 0 0 11.4M17.7 6.3a8 8 0 0 1 0 11.4"/><path d="M3.5 3.5a14 14 0 0 0 0 17M20.5 3.5a14 14 0 0 1 0 17"/></svg>
}
function IconCalendar() {
  return <svg width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
}
