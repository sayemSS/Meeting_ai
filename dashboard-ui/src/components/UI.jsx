import React from 'react'

// ── StateBadge ──────────────────────────────────────────────
const STATE_COLORS = {
  completed:    { bg: 'rgba(34,197,94,0.12)',   color: '#22C55E' },
  active:       { bg: 'rgba(59,130,246,0.12)',  color: '#3B82F6' },
  joining:      { bg: 'rgba(59,130,246,0.12)',  color: '#3B82F6' },
  leaving:      { bg: 'rgba(59,130,246,0.12)',  color: '#3B82F6' },
  transcribing: { bg: 'rgba(59,130,246,0.12)',  color: '#3B82F6' },
  summarizing:  { bg: 'rgba(59,130,246,0.12)',  color: '#3B82F6' },
  recording_done:{ bg: 'rgba(56,189,248,0.12)', color: '#38BDF8' },
  pending:      { bg: 'rgba(245,158,11,0.12)',  color: '#F59E0B' },
  scheduled:    { bg: 'rgba(245,158,11,0.12)',  color: '#F59E0B' },
  failed:       { bg: 'rgba(239,68,68,0.12)',   color: '#EF4444' },
  cancelled:    { bg: 'rgba(139,149,165,0.12)', color: '#8B95A5' },
}
const PULSE_STATES = new Set(['active', 'joining', 'transcribing', 'summarizing'])

export function StateBadge({ state }) {
  const s = state || 'pending'
  const { bg, color } = STATE_COLORS[s] || STATE_COLORS.pending
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 9px', borderRadius: 20,
      background: bg, color,
      fontSize: 11, fontWeight: 600,
      letterSpacing: 0.2, textTransform: 'uppercase',
      fontFamily: 'var(--mono)',
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0,
        animation: PULSE_STATES.has(s) ? 'mp-pulse 1.5s infinite' : 'none',
      }} />
      {s}
    </span>
  )
}

// ── Button ──────────────────────────────────────────────────
const BTN_VARIANTS = {
  primary: { background: '#3B82F6', color: '#fff', border: 'none' },
  ghost:   { background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border2)' },
  danger:  { background: 'rgba(239,68,68,0.12)', color: '#EF4444', border: '1px solid rgba(239,68,68,0.3)' },
}

export function Button({ variant = 'ghost', size = 'md', onClick, disabled, children, style }) {
  const base = BTN_VARIANTS[variant]
  const pad = size === 'sm' ? '5px 10px' : '8px 14px'
  const fs  = size === 'sm' ? 12 : 13
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 7,
        padding: pad, borderRadius: 'var(--radius)',
        fontSize: fs, fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'opacity .15s, transform .1s', whiteSpace: 'nowrap',
        opacity: disabled ? 0.5 : 1,
        ...base, ...style,
      }}
    >
      {children}
    </button>
  )
}

// ── Card ────────────────────────────────────────────────────
export function Card({ children, style }) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)', padding: 20, ...style,
    }}>
      {children}
    </div>
  )
}

// ── Loading ─────────────────────────────────────────────────
export function Loading() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
      <span style={{ display: 'inline-flex', gap: 4 }}>
        {[0, 0.2, 0.4].map((d, i) => (
          <span key={i} style={{
            width: 7, height: 7, borderRadius: '50%', background: 'var(--accent)',
            animation: `mp-blink 1.2s ${d}s infinite`,
          }} />
        ))}
      </span>
    </div>
  )
}

// ── EmptyState ──────────────────────────────────────────────
export function EmptyState({ icon = '📭', title, subtitle, action }) {
  return (
    <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--muted)' }}>
      <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.4 }}>{icon}</div>
      {title && <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 6 }}>{title}</div>}
      {subtitle && <div style={{ fontSize: 13 }}>{subtitle}</div>}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  )
}

// ── ErrorBanner ─────────────────────────────────────────────
export function ErrorBanner({ message }) {
  if (!message) return null
  return (
    <div style={{
      background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
      borderRadius: 'var(--radius)', padding: '12px 16px', color: 'var(--danger)',
      fontSize: 13, marginBottom: 16, display: 'flex', gap: 8,
    }}>
      ⚠ {message}
    </div>
  )
}

// ── SuccessBanner ───────────────────────────────────────────
export function SuccessBanner({ message }) {
  if (!message) return null
  return (
    <div style={{
      background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)',
      borderRadius: 'var(--radius)', padding: '12px 16px', color: 'var(--success)',
      fontSize: 13, marginBottom: 16,
    }}>
      ✓ {message}
    </div>
  )
}

// ── ParticipantChips ────────────────────────────────────────
export function ParticipantChips({ names = [], max = 4 }) {
  const visible = names.slice(0, max)
  const extra = names.length - max
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
      {visible.map((n, i) => (
        <span key={i} style={{
          background: 'var(--surface2)', borderRadius: 16,
          padding: '2px 9px', fontSize: 11, color: 'var(--muted)',
          border: '1px solid var(--border)',
        }}>{n}</span>
      ))}
      {extra > 0 && (
        <span style={{
          background: 'var(--surface2)', borderRadius: 16,
          padding: '2px 9px', fontSize: 11, color: 'var(--muted2)',
          border: '1px solid var(--border)',
        }}>+{extra}</span>
      )}
    </div>
  )
}

// ── FormField ───────────────────────────────────────────────
export function FormField({ label, required, hint, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      {label && (
        <label style={{
          display: 'block', fontSize: 11, fontWeight: 500,
          color: 'var(--muted)', marginBottom: 6,
          letterSpacing: 0.4, textTransform: 'uppercase',
        }}>
          {label}
          {required && <span style={{ color: 'var(--danger)', marginLeft: 3 }}>*</span>}
        </label>
      )}
      {children}
      {hint && <div style={{ fontSize: 11, color: 'var(--muted2)', marginTop: 5 }}>{hint}</div>}
    </div>
  )
}

// ── Input / Select ──────────────────────────────────────────
const INPUT_STYLE = {
  width: '100%', background: 'var(--surface2)',
  border: '1px solid var(--border2)', borderRadius: 'var(--radius)',
  color: 'var(--text)', padding: '10px 12px', fontSize: 14,
  outline: 'none', transition: 'border-color .15s',
}

export function Input({ style, ...props }) {
  const [focus, setFocus] = React.useState(false)
  return (
    <input
      {...props}
      onFocus={() => setFocus(true)}
      onBlur={() => setFocus(false)}
      style={{
        ...INPUT_STYLE,
        borderColor: focus ? 'var(--accent)' : 'var(--border2)',
        ...style,
      }}
    />
  )
}

export function Select({ children, style, ...props }) {
  const [focus, setFocus] = React.useState(false)
  return (
    <select
      {...props}
      onFocus={() => setFocus(true)}
      onBlur={() => setFocus(false)}
      style={{
        ...INPUT_STYLE,
        borderColor: focus ? 'var(--accent)' : 'var(--border2)',
        ...style,
      }}
    >
      {children}
    </select>
  )
}

// ── Keyframe styles injected once ───────────────────────────
const STYLES = `
@keyframes mp-pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
@keyframes mp-blink  { 0%,80%,100%{opacity:.2} 40%{opacity:1} }
`
if (typeof document !== 'undefined' && !document.getElementById('mp-keyframes')) {
  const s = document.createElement('style')
  s.id = 'mp-keyframes'
  s.textContent = STYLES
  document.head.appendChild(s)
}
