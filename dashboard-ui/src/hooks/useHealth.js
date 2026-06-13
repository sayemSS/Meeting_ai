import { useState, useEffect } from 'react'
import { api } from '../utils/api'

export function useHealth() {
  const [health, setHealth] = useState({ status: 'checking', active_sessions: 0 })

  useEffect(() => {
    const check = async () => {
      try {
        const d = await api.health()
        setHealth({ ...d, ok: true })
      } catch {
        setHealth({ status: 'offline', active_sessions: 0, ok: false })
      }
    }
    check()
    const t = setInterval(check, 15000)
    return () => clearInterval(t)
  }, [])

  return health
}
