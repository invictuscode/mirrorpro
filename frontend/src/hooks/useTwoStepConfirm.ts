import { useCallback, useEffect, useRef, useState } from 'react'

export interface TwoStepConfirm {
  pending: boolean
  /** First call arms; a second call within `timeoutMs` runs the action. */
  trigger: () => void
}

/** Guards destructive actions (e.g. ending a session) against a single
 * accidental press, without a modal dialog. */
export function useTwoStepConfirm(action: () => void, timeoutMs = 4000): TwoStepConfirm {
  const [pending, setPending] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const trigger = useCallback(() => {
    window.clearTimeout(timer.current)
    if (pending) {
      setPending(false)
      action()
      return
    }
    setPending(true)
    timer.current = window.setTimeout(() => setPending(false), timeoutMs)
  }, [pending, action, timeoutMs])

  return { pending, trigger }
}
