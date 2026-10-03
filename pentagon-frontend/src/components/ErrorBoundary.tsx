import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Pentagon render error', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <main className="grid min-h-dvh place-items-center bg-[#000000] px-6 text-zinc-100">
        <section className="w-full max-w-[460px] rounded-2xl border border-white/[0.08] bg-[#101010] p-7 shadow-[0_24px_70px_rgba(0,0,0,.5)]">
          <p className="mb-2 text-caption font-medium uppercase tracking-[.2em] text-zinc-600">
            Something went wrong
          </p>
          <h1 className="text-hero font-medium tracking-[-.01em] text-zinc-100">
            The interface hit an unexpected error.
          </h1>
          <p className="mt-2.5 text-body leading-5 text-zinc-500">
            Your conversations are saved on the server and are unaffected. Reloading usually
            clears this.
          </p>
          {error.message ? (
            <pre className="mt-4 max-h-32 overflow-auto rounded-lg border border-white/[0.06] bg-black/30 px-3 py-2 text-micro leading-4 text-zinc-600">
              {error.message}
            </pre>
          ) : null}
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-5 h-10 rounded-xl bg-emerald-300 px-4 text-small font-semibold text-[#000000] transition hover:bg-emerald-200"
          >
            Reload Pentagon
          </button>
        </section>
      </main>
    )
  }
}