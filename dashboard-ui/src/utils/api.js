const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  base: BASE,

  health: ()                    => request('/health'),
  languages: ()                 => request('/config/languages'),

  createMeeting: (body)         => request('/meetings', { method: 'POST', body: JSON.stringify(body) }),
  bulkCreate: (meetings)        => request('/meetings/bulk', { method: 'POST', body: JSON.stringify({ meetings }) }),

  meetings: ()                  => request('/meetings'),
  searchMeetings: (params)      => request(`/meetings/search?${params}`),
  upcoming: ()                  => request('/meetings/upcoming'),

  liveSessions: ()              => request('/sessions/live'),
  stopSession: (id)             => request(`/sessions/${id}/stop`, { method: 'POST' }),

  meeting: (id)                 => request(`/meetings/${id}`),
  metadata: (id)                => request(`/meetings/${id}/metadata`),
  transcript: (id)              => request(`/meetings/${id}/transcript`),
  captions: (id)                => request(`/meetings/${id}/captions`),
  summary: (id)                 => request(`/meetings/${id}/summary`),
  quickSummary: (id)            => request(`/meetings/${id}/quick-summary`, { method: 'POST' }),
  getQuickSummary: (id)         => request(`/meetings/${id}/quick-summary`),
  reportUrl: (id)               => `${BASE}/meetings/${id}/report.pdf`,
}