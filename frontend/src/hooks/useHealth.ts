import { useState, useEffect, useCallback } from 'react'
import { healthCheck, type HealthResponse } from '../lib/api'

export function useHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const check = useCallback(async () => {
    try {
      setLoading(true)
      const data = await healthCheck()
      setHealth(data)
      setError(null)
    } catch {
      setError('Backend offline')
      setHealth(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    check()
    const interval = setInterval(check, 30000)
    return () => clearInterval(interval)
  }, [check])

  return { health, loading, error, refresh: check }
}
