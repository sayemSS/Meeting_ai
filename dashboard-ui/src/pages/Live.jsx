import React, { useCallback } from 'react'
import { api } from '../utils/api'
import { usePoll } from '../hooks/usePoll'
import {
  StateBadge, Button, Loading, EmptyState, ErrorBanner, ParticipantChips,
} from '../components/UI'
import { fmtDate } from '../utils/format'

export default function Live() {
  const fetchLive    = useCallback(() => api.liveSessions(), [])
  const fetchUpcoming = useCallback(() => api.upcoming(), [])

  const live     = usePoll(fetchLive, 10000)
  const upcoming = usePoll(fetchUpcoming, 30000)

  const stop = async (id) => {
    if (!confirm('Stop this session?')) return
    try { await api.stopSession(id); live.refresh() }
    catch (e) { alert('Error: ' + e.message) }
  }

  return (
    <div style={{ padding: '24px 28px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, flex: 1 }}>Live sessions</h1>
        <span style={{ fontSize: 12, color: 'var(--muted2)' }}>Auto-refresh 10s</span>
        <Button size="sm" onClick={live.refresh}>↺ Refresh</Button>
      </div>

      <ErrorBanner message={live.error} />
      {live.loading ? <Loading /> : (
        !live.data?.sessions?.length
          ? <EmptyState icon="📡" title="No active sessions" subtitle="Start a meeting to see it here" />
          : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16, marginBottom: 32 }}>
              {live.data.sessions.map(s => (
                <LiveCard key={s.session_id} session={s} onStop={stop} />
              ))}
            </div>
      )}

      <div style={{
        fontSize: 11, fontWeight: 600, color: 'var(--muted2)',
        textTransform: 'uppercase', letterSpacing: 0.6,
        fontFamily: 'var(--mono)', margin: '8px 0 14px',
        borderTop: '1px solid var(--border)', paddingTop: 20,
      }}>
        Scheduled / upcoming
      </div>

      {upcoming.loading ? <Loading /> : (
        !upcoming.data?.meetings?.length
          ? <p style={{ color: 'var(--muted2)', fontSize: 13 }}>No upcoming meetings scheduled.</p>
          : <UpcomingTable meetings={upcoming.data.meetings} />
      )}
    </div>
  )
}

function LiveCard({ session: s, onStop }) {
  const isActive = ['active', 'joining', 'transcribing'].includes(s.state)
  return (
    <div style={{
      background: 'var(--surface)',
      border: `1px solid ${isActive ? 'rgba(59,130,246,0.4)' : 'var(--border)'}`,
      borderRadius: 12, padding: 18, transition: 'border-color .2s',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>{s.title}</div>
          <StateBadge state={s.state} />
        </div>
        <Button variant="danger" size="sm" onClick={() => onStop(s.session_id)}>■ Stop</Button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, margin: '14px 0' }}>
        <Stat value={s.participants?.length ?? 0} label="Now" color="var(--accent)" />
        <Stat value={s.peak_participants ?? 0} label="Peak" />
        <Stat value={s.captions ?? 0} label="Captions" color="var(--muted)" />
      </div>

      {s.participants?.length > 0 && (
        <ParticipantChips names={s.participants} max={4} />
      )}
      {s.error && (
        <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 8 }}>⚠ {s.error}</div>
      )}
    </div>
  )
}

function Stat({ value, label, color = 'var(--text)' }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--mono)', color }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', marginTop: 2, fontFamily: 'var(--mono)' }}>
        {label}
      </div>
    </div>
  )
}

function UpcomingTable({ meetings }) {
  return (
    <div style={{ overflowX: 'auto', borderRadius: 10, border: '1px solid var(--border)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {['Title', 'Start time', 'Duration', 'Language'].map(h => (
              <th key={h} style={{
                textAlign: 'left', padding: '11px 16px',
                fontSize: 11, fontWeight: 600, color: 'var(--muted)',
                textTransform: 'uppercase', letterSpacing: 0.5,
                background: 'var(--surface2)', borderBottom: '1px solid var(--border)',
                fontFamily: 'var(--mono)',
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {meetings.map(m => (
            <tr key={m.id}>
              <td style={{ padding: '12px 16px', fontWeight: 500 }}>{m.title}</td>
              <td style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)' }}>
                {fmtDate(m.start_time)}
              </td>
              <td style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)' }}>
                {m.duration_minutes ?? 60} min
              </td>
              <td style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)' }}>
                {m.language || 'auto'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
