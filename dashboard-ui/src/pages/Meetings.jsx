import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../utils/api'
import { StateBadge, Button, Loading, EmptyState, ErrorBanner, ParticipantChips, Input } from '../components/UI'
import { fmtDate, fmtDuration } from '../utils/format'

export default function Meetings() {
  const navigate = useNavigate()
  const [meetings, setMeetings] = useState([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const debounceRef = useRef(null)

  const load = useCallback(async (nameQ = '', fromQ = '', toQ = '') => {
    setLoading(true); setError('')
    try {
      const params = new URLSearchParams()
      if (nameQ) params.set('name', nameQ)
      if (fromQ) params.set('date_from', new Date(fromQ).toISOString())
      if (toQ)   params.set('date_to', new Date(toQ + 'T23:59:59').toISOString())
      const url = params.toString() ? `/meetings/search?${params}` : null
      const d = url ? await api.searchMeetings(params) : await api.meetings()
      setMeetings(d.meetings || [])
      setCount(d.count ?? (d.meetings || []).length)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const onNameChange = (e) => {
    setName(e.target.value)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => load(e.target.value, dateFrom, dateTo), 350)
  }
  const onDateChange = (from, to) => {
    setDateFrom(from); setDateTo(to)
    load(name, from, to)
  }
  const clearFilters = () => {
    setName(''); setDateFrom(''); setDateTo(''); load()
  }

  return (
    <div style={{ padding: '24px 28px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, flex: 1 }}>Meetings</h1>
        <Button variant="primary" size="sm" onClick={() => navigate('/new')}>+ New</Button>
      </div>

      {/* Search bar */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 18 }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 200, maxWidth: 300 }}>
          <svg style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--muted2)', pointerEvents: 'none' }}
            width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <Input
            value={name} onChange={onNameChange}
            placeholder="Search by name…"
            style={{ paddingLeft: 32 }}
          />
        </div>
        <Input type="date" value={dateFrom}
          onChange={e => onDateChange(e.target.value, dateTo)}
          style={{ width: 150 }}
        />
        <span style={{ color: 'var(--muted2)', fontSize: 12 }}>→</span>
        <Input type="date" value={dateTo}
          onChange={e => onDateChange(dateFrom, e.target.value)}
          style={{ width: 150 }}
        />
        <Button size="sm" onClick={clearFilters}>Clear</Button>
      </div>

      <ErrorBanner message={error} />

      {loading ? <Loading /> : meetings.length === 0
        ? <EmptyState icon="📅" title="No meetings found" subtitle="Try clearing your filters or create a new meeting" />
        : (
          <div style={{ overflowX: 'auto', borderRadius: 10, border: '1px solid var(--border)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Title', 'Date', 'Duration', 'Participants', 'Language', 'State'].map(h => (
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
                  <tr key={m.session_id}
                    onClick={() => navigate(`/meetings/${m.session_id}`)}
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={e => e.currentTarget.querySelectorAll('td').forEach(td => td.style.background = 'var(--surface2)')}
                    onMouseLeave={e => e.currentTarget.querySelectorAll('td').forEach(td => td.style.background = '')}
                  >
                    <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                      <div style={{ fontWeight: 500 }}>{m.title}</div>
                      <div style={{ fontSize: 11, color: 'var(--muted2)', marginTop: 2, fontFamily: 'var(--mono)' }}>
                        {m.session_id}
                      </div>
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>
                      {fmtDate(m.date)}
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>
                      {fmtDuration(m.duration_seconds)}
                    </td>
                    <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                      <ParticipantChips names={m.participants || []} max={3} />
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>
                      {m.language || '—'}
                    </td>
                    <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                      <StateBadge state={m.state} />
                      {m.error && <div style={{ color: 'var(--danger)', fontSize: 11, marginTop: 3 }}>{m.error}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
      {!loading && (
        <div style={{ fontSize: 11, color: 'var(--muted2)', marginTop: 10, fontFamily: 'var(--mono)' }}>
          {count} meeting{count !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  )
}
