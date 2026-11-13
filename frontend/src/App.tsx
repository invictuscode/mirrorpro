import { useSyncExternalStore } from 'react'

import { ErrorBoundary } from './components/ErrorBoundary'
import { DevPage } from './pages/DevPage'
import { MirrorPage } from './pages/MirrorPage'
import { TherapistPage } from './pages/TherapistPage'

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

/** Hash routes: `#/` mirror (patient-facing), `#/dev` developer console,
 * `#/therapist` custom-exercise authoring. */
export function App() {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  const route = hash.startsWith('#/dev') ? 'dev' : hash.startsWith('#/therapist') ? 'therapist' : 'mirror'
  // Keyed by route so navigating away from a crashed page recovers it.
  return (
    <ErrorBoundary key={route}>
      {route === 'dev' ? <DevPage /> : route === 'therapist' ? <TherapistPage /> : <MirrorPage />}
    </ErrorBoundary>
  )
}
