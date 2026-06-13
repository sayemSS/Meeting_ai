import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../utils/api'
import {
  Card, Button, FormField, Input, Select,
  ErrorBanner, SuccessBanner,
} from '../components/UI'

export default function NewMeeting() {
  const navigate = useNavigate()
  const [languages, setLanguages] = useState([])
  const [defaultLang, setDefaultLang] = useState('auto')
  const [form, setForm] = useState({
    title: '', meet_url: '', start_time: '', duration_minutes: '', language: 'auto',
  })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.languages().then(d => {
      setLanguages(d.languages || [])
      setDefaultLang(d.default || 'auto')
      setForm(f => ({ ...f, language: d.default || 'auto' }))
    }).catch(() => {})
  }, [])

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  const handleSubmit = async () => {
    setError(''); setSuccess('')
    if (!form.title.trim()) { setError('Meeting name is required.'); return }
    if (!form.meet_url.trim()) { setError('Meeting link is required.'); return }

    const body = {
      title: form.title.trim(),
      meet_url: form.meet_url.trim(),
      language: form.language,
      duration_minutes: form.duration_minutes ? parseInt(form.duration_minutes) : 60,
    }
    if (form.start_time) body.start_time = new Date(form.start_time).toISOString()

    setLoading(true)
    try {
      const d = await api.createMeeting(body)
      setSuccess(`"${d.title}" ${d.mode === 'started' ? 'started now' : 'scheduled'}! (${d.session_id})`)
      setForm({ title: '', meet_url: '', start_time: '', duration_minutes: '', language: defaultLang })
      setTimeout(() => navigate(d.mode === 'started' ? '/live' : '/meetings'), 1400)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '24px 28px', maxWidth: 680 }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 6 }}>New Meeting</h1>
      <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 24 }}>
        Schedule a bot or start one immediately.
      </p>

      <ErrorBanner message={error} />
      <SuccessBanner message={success} />

      <Card>
        {/* Name + URL side by side */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <FormField label="Meeting name" required>
            <Input
              value={form.title}
              onChange={set('title')}
              placeholder="e.g. Q2 Sales Review"
            />
          </FormField>
          <FormField label="Google Meet link" required>
            <Input
              type="url"
              value={form.meet_url}
              onChange={set('meet_url')}
              placeholder="https://meet.google.com/xxx"
            />
          </FormField>
        </div>

        <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '4px 0 20px' }} />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <FormField label="Start time" hint="Leave empty to start now">
            <Input type="datetime-local" value={form.start_time} onChange={set('start_time')} />
          </FormField>
          <FormField label="Duration (minutes)" hint="Default 60 min">
            <Input
              type="number" min="5" max="480"
              value={form.duration_minutes}
              onChange={set('duration_minutes')}
              placeholder="Default 60 min"
            />
          </FormField>
        </div>

        <FormField label="Language">
          <Select value={form.language} onChange={set('language')}>
            {languages.length === 0
              ? <option value="auto">Auto-detect</option>
              : languages.map(l => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))
            }
          </Select>
        </FormField>

        <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
          <Button variant="primary" onClick={handleSubmit} disabled={loading}>
            {loading ? 'Starting…' : '▶ Start meeting'}
          </Button>
          <Button variant="ghost" onClick={() =>
            setForm({ title: '', meet_url: '', start_time: '', duration_minutes: '', language: defaultLang })
          }>
            Clear
          </Button>
        </div>
      </Card>
    </div>
  )
}
