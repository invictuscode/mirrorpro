import { useEffect, useState } from 'react'

/** performance.now(), refreshed every `intervalMs` while `active`. */
export function useNow(intervalMs: number, active = true): number {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    if (!active) return
    const t = window.setInterval(() => setNow(performance.now()), intervalMs)
    return () => window.clearInterval(t)
  }, [intervalMs, active])
  return now
}
