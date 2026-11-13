import { Component, type ErrorInfo, type ReactNode } from 'react'

interface State {
  error: Error | null
}

/**
 * Last line of defence: a rendering error must never leave a blank (black)
 * screen, which on a mirror is indistinguishable from "switched off".
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('UI crashed', error, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children
    return (
      <div className="crash" role="alert">
        <h1>Something went wrong on this screen</h1>
        <p>
          The display hit an unexpected error. This can happen if the app and the tracking service are different
          versions. Restart both, then reload.
        </p>
        <pre>{this.state.error.message}</pre>
        <button onClick={() => window.location.reload()}>Reload</button>
      </div>
    )
  }
}
