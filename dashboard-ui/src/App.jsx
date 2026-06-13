import React, { useState, useEffect, useCallback } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import NewMeeting from './pages/NewMeeting'
import Live from './pages/Live'
import Meetings from './pages/Meetings'
import MeetingDetail from './pages/MeetingDetail'
import { api } from './utils/api'

export default function App() {
  const [liveCounts, setLiveCounts] = useState(0)

  useEffect(() => {
    const poll = async () => {
      try {
        const d = await api.liveSessions()
        setLiveCounts((d.sessions || []).length)
      } catch {}
    }
    poll()
    const t = setInterval(poll, 15000)
    return () => clearInterval(t)
  }, [])

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar liveCounts={liveCounts} />
      <main style={{ flex: 1, overflowY: 'auto' }}>
        <Routes>
          <Route path="/" element={<Navigate to="/meetings" replace />} />
          <Route path="/new" element={<NewMeeting />} />
          <Route path="/live" element={<Live />} />
          <Route path="/meetings" element={<Meetings />} />
          <Route path="/meetings/:id" element={<MeetingDetail />} />
        </Routes>
      </main>
    </div>
  )
}
