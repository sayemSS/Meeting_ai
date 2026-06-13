import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../utils/api'
import { StateBadge, Button, Loading, EmptyState, ErrorBanner, ParticipantChips } from '../components/UI'
import { fmtDate, fmtDuration, fmtTimestamp } from '../utils/format'

export default function MeetingDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('summary')
  const [transcript, setTranscript] = useState(null)
  const [txLoading, setTxLoading] = useState(false)
  const [txError, setTxError] = useState('')
  const [captions, setCaptions] = useState([])
  const [capLive, setCapLive] = useState(false)
  const [capError, setCapError] = useState('')
  const [quick, setQuick] = useState(null)
  const [quickLoading, setQuickLoading] = useState(false)
  const [quickError, setQuickError] = useState('')

  useEffect(() => {
    api.meeting(id)
      .then(setData)
      .catch(e => setError(e.message))
    // Show a previously generated quick summary if one exists (ignore 404).
    api.getQuickSummary(id).then(setQuick).catch(() => {})
  }, [id])

  const genQuickSummary = async () => {
    setQuickLoading(true); setQuickError('')
    try {
      const res = await api.quickSummary(id)
      setQuick(res.summary)
    } catch (e) {
      setQuickError(e.message.includes('404')
        ? 'No captions captured yet (are Meet captions ON?).'
        : e.message)
    } finally {
      setQuickLoading(false)
    }
  }

  // Poll captions while the Captions tab is open and the meeting is still live.
  useEffect(() => {
    if (tab !== 'captions') return
    let active = true
    let timer
    const poll = async () => {
      try {
        const d = await api.captions(id)
        if (!active) return
        setCaptions(d.captions || [])
        setCapLive(!!d.live)
        setCapError('')
        if (d.live) {
          timer = setTimeout(poll, 4000)          // keep refreshing while live
        } else {
          api.meeting(id).then(setData).catch(() => {})  // meeting ended: pull transcript/summary
        }
      } catch (e) {
        if (active) setCapError(e.message)
      }
    }
    poll()
    return () => { active = false; clearTimeout(timer) }
  }, [tab, id])

  const loadTranscript = async () => {
    if (transcript) return
    setTxLoading(true); setTxError('')
    try {
      const t = await api.transcript(id)
      setTranscript(t)
    } catch (e) {
      setTxError(e.message.includes('404') ? 'Transcript not available yet.' : e.message)
    } finally {
      setTxLoading(false)
    }
  }

  const switchTab = (t) => {
    setTab(t)
    if (t === 'transcript') loadTranscript()
  }

  if (error) return (
    <div style={{ padding: '24px 28px' }}>
      <ErrorBanner message={error} />
      <Button onClick={() => navigate('/meetings')}>← Back</Button>
    </div>
  )
  if (!data) return <Loading />

  const { metadata: meta, summary } = data

  return (
    <div style={{ padding: '24px 28px' }}>
      {/* Back */}
      <div
        onClick={() => navigate('/meetings')}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--muted)', fontSize: 13, cursor: 'pointer', marginBottom: 20 }}
      >
        <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>
        Back to meetings
      </div>

      {/* Header card */}
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 12, padding: 22, marginBottom: 20,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{meta.title}</div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <StateBadge state={meta.state} />
            <button
              onClick={genQuickSummary}
              disabled={quickLoading}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                padding: '5px 12px', borderRadius: 8,
                background: 'var(--accent-dim)', border: '1px solid var(--border2)',
                color: 'var(--accent)', fontSize: 12, fontWeight: 500,
                cursor: quickLoading ? 'wait' : 'pointer',
              }}
            >
              ⚡ {quickLoading ? 'Generating…' : 'Quick summary'}
            </button>
            <a
              href={api.reportUrl(id)}
              target="_blank"
              rel="noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                padding: '5px 12px', borderRadius: 8,
                background: 'transparent', border: '1px solid var(--border2)',
                color: 'var(--muted)', fontSize: 12, fontWeight: 500,
              }}
            >
              <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download PDF
            </a>
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, marginTop: 14, alignItems: 'center' }}>
          <MetaItem icon="📅">{fmtDate(meta.actual_start || meta.scheduled_start)}</MetaItem>
          <MetaItem icon="⏱">{fmtDuration(meta.duration_seconds)}</MetaItem>
          {meta.language && <MetaItem icon="🌐">Language: {meta.language}</MetaItem>}
          <MetaItem icon="👥">{(meta.unique_participants || []).length} participants (peak: {meta.peak_participant_count || 0})</MetaItem>
          {meta.meet_url && (
            <a href={meta.meet_url} target="_blank" rel="noreferrer"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: 'var(--accent)', fontSize: 12 }}>
              🔗 Join link
            </a>
          )}
        </div>

        {(meta.unique_participants || []).length > 0 && (
          <div style={{ marginTop: 14 }}>
            <ParticipantChips names={meta.unique_participants} max={10} />
          </div>
        )}

        {meta.error && (
          <div style={{ marginTop: 14, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: 'var(--danger)', fontSize: 13 }}>
            ⚠ {meta.error}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
        {['summary', 'transcript', 'captions'].map(t => (
          <div key={t} onClick={() => switchTab(t)} style={{
            padding: '10px 18px', fontSize: 13, fontWeight: 500, cursor: 'pointer',
            color: tab === t ? 'var(--accent)' : 'var(--muted)',
            borderBottom: `2px solid ${tab === t ? 'var(--accent)' : 'transparent'}`,
            marginBottom: -1, textTransform: 'capitalize', transition: 'color .15s',
          }}>
            {t}
          </div>
        ))}
      </div>

      {tab === 'summary' && (
        summary
          ? <SummaryTab summary={summary} />
          : quick
            ? <div>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16,
                  background: 'var(--accent-dim)', border: '1px solid var(--border2)',
                  borderRadius: 8, padding: '9px 14px', fontSize: 12, color: 'var(--accent)',
                }}>
                  ⚡ Quick summary from captions (preview). The final summary
                  will replace this once audio processing finishes.
                </div>
                <SummaryTab summary={quick} />
              </div>
            : <div>
                {quickError && <ErrorBanner message={quickError} />}
                <EmptyState
                  icon="⏳"
                  title="Summary not ready"
                  subtitle="The meeting may still be processing. You can generate a quick summary from captions now using the ⚡ button above."
                />
              </div>
      )}
      {tab === 'transcript' && (
        txLoading ? <Loading /> :
        txError ? <ErrorBanner message={txError} /> :
        transcript ? <TranscriptTab transcript={transcript} /> :
        <EmptyState icon="📝" title="No transcript yet" subtitle="Transcript will appear after the meeting ends." />
      )}
      {tab === 'captions' && (
        capError ? <ErrorBanner message={capError} /> :
        <CaptionsTab captions={captions} live={capLive} />
      )}
    </div>
  )
}

function MetaItem({ icon, children }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
      <span>{icon}</span>{children}
    </div>
  )
}

// ── Summary tab ──────────────────────────────────────────────
function SummaryTab({ summary }) {
  if (!summary) return (
    <EmptyState icon="⏳" title="Summary not ready" subtitle="The meeting may still be processing…" />
  )

  return (
    <div>
      {/* Overview */}
      <Section title="Overview">
        <div style={{
          fontSize: 14, lineHeight: 1.7,
          background: 'var(--surface2)', borderRadius: 8, padding: 16,
          borderLeft: '3px solid var(--accent)',
        }}>
          {summary.overview}
        </div>
      </Section>

      {/* Sentiment */}
      {summary.sentiment && (
        <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted2)', textTransform: 'uppercase', fontFamily: 'var(--mono)' }}>Sentiment</span>
          <SentimentBadge sentiment={summary.sentiment} />
        </div>
      )}

      <BulletSection title="Key points" items={summary.key_points} />
      <BulletSection title="Decisions" items={summary.decisions} />

      {/* Action items */}
      {summary.action_items?.length > 0 && (
        <Section title="Action items">
          <div style={{ overflowX: 'auto', borderRadius: 8, border: '1px solid var(--border)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Task', 'Owner', 'Due'].map(h => (
                    <th key={h} style={{
                      textAlign: 'left', padding: '8px 14px',
                      fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                      background: 'var(--surface2)', borderBottom: '1px solid var(--border)',
                      fontFamily: 'var(--mono)',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {summary.action_items.map((a, i) => (
                  <tr key={i}>
                    <td style={{ padding: '10px 14px', fontSize: 13, borderBottom: i < summary.action_items.length - 1 ? '1px solid var(--border)' : 'none' }}>
                      {a.description}
                    </td>
                    <td style={{ padding: '10px 14px', borderBottom: i < summary.action_items.length - 1 ? '1px solid var(--border)' : 'none' }}>
                      {a.owner
                        ? <span style={{ background: 'var(--accent-dim)', color: 'var(--accent)', padding: '2px 8px', borderRadius: 4, fontSize: 11 }}>{a.owner}</span>
                        : <span style={{ color: 'var(--muted2)' }}>—</span>
                      }
                    </td>
                    <td style={{ padding: '10px 14px', borderBottom: i < summary.action_items.length - 1 ? '1px solid var(--border)' : 'none' }}>
                      {a.due
                        ? <span style={{ background: 'rgba(245,158,11,0.12)', color: 'var(--warning)', padding: '2px 8px', borderRadius: 4, fontSize: 11, fontFamily: 'var(--mono)' }}>{a.due}</span>
                        : <span style={{ color: 'var(--muted2)' }}>—</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <BulletSection title="Risks" items={summary.risks} />
      <BulletSection title="Next steps" items={summary.next_steps} />

      {summary.generated_at && (
        <div style={{ fontSize: 11, color: 'var(--muted2)', fontFamily: 'var(--mono)', marginTop: 16 }}>
          Generated: {fmtDate(summary.generated_at)}
        </div>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{
        fontSize: 11, fontWeight: 600, color: 'var(--muted2)',
        textTransform: 'uppercase', letterSpacing: 0.6,
        fontFamily: 'var(--mono)', marginBottom: 10,
      }}>{title}</div>
      {children}
    </div>
  )
}

function BulletSection({ title, items }) {
  if (!items?.length) return null
  return (
    <Section title={title}>
      <ul style={{ listStyle: 'none' }}>
        {items.map((item, i) => (
          <li key={i} style={{
            display: 'flex', gap: 10, padding: '9px 0',
            borderBottom: i < items.length - 1 ? '1px solid var(--border)' : 'none',
            fontSize: 13,
          }}>
            <span style={{ color: 'var(--accent)', flexShrink: 0, marginTop: 1 }}>›</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </Section>
  )
}

function SentimentBadge({ sentiment }) {
  const map = {
    positive: { bg: 'rgba(34,197,94,0.12)',   color: '#22C55E' },
    negative: { bg: 'rgba(239,68,68,0.12)',   color: '#EF4444' },
    neutral:  { bg: 'rgba(139,149,165,0.12)', color: '#8B95A5' },
    mixed:    { bg: 'rgba(245,158,11,0.12)',  color: '#F59E0B' },
  }
  const { bg, color } = map[sentiment] || map.neutral
  return (
    <span style={{ background: bg, color, padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, textTransform: 'capitalize' }}>
      {sentiment}
    </span>
  )
}

// ── Captions tab (live) ──────────────────────────────────────
function CaptionsTab({ captions, live }) {
  if (!captions.length) return (
    <EmptyState
      icon="💬"
      title={live ? 'Waiting for captions…' : 'No captions captured'}
      subtitle={live
        ? 'Live captions appear here as people speak (Meet captions must be ON).'
        : 'Nothing was captured for this meeting.'}
    />
  )
  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14, fontFamily: 'var(--mono)', display: 'flex', alignItems: 'center', gap: 8 }}>
        {live && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#EF4444', display: 'inline-block', animation: 'pulse 1.5s infinite' }} />}
        {live ? 'LIVE' : 'Final'} · {captions.length} lines
        {live && <span style={{ color: 'var(--muted2)' }}>· refreshing…</span>}
      </div>
      {captions.map((c, i) => (
        <div key={i} style={{
          display: 'flex', gap: 14, padding: '8px 0',
          borderBottom: i < captions.length - 1 ? '1px solid var(--border)' : 'none',
          fontSize: 13,
        }}>
          <div style={{ minWidth: 110, fontWeight: 500, fontSize: 12, color: 'var(--accent)', flexShrink: 0 }}>
            {c.speaker || 'Unknown'}
          </div>
          <div style={{ flex: 1, lineHeight: 1.6 }}>{c.text}</div>
        </div>
      ))}
    </div>
  )
}

// ── Transcript tab ───────────────────────────────────────────
function TranscriptTab({ transcript: t }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14, fontFamily: 'var(--mono)' }}>
        Language: {t.language || 'unknown'} · Duration: {fmtDuration(t.duration)} · {t.segments?.length || 0} segments
      </div>
      {t.segments?.map((seg, i) => (
        <div key={i} style={{
          display: 'flex', gap: 14, padding: '9px 0',
          borderBottom: i < t.segments.length - 1 ? '1px solid var(--border)' : 'none',
          fontSize: 13,
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted2)', minWidth: 90, paddingTop: 2 }}>
            {fmtTimestamp(seg.start)} – {fmtTimestamp(seg.end)}
          </div>
          <div style={{ minWidth: 90, fontWeight: 500, fontSize: 12, color: seg.speaker ? 'var(--accent)' : 'var(--muted2)', flexShrink: 0 }}>
            {seg.speaker || 'Unknown'}
          </div>
          <div style={{ flex: 1, lineHeight: 1.6 }}>{seg.text}</div>
        </div>
      ))}
    </div>
  )
}