import { useEffect, useState } from 'react'
import './App.css'

function App() {
  const [health, setHealth] = useState({ status: 'checking', data: null, error: '' })
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function checkHealth() {
      setHealth({ status: 'checking', data: null, error: '' })
      try {
        const response = await fetch('/api/health', { signal: controller.signal })
        const data = await response.json()
        if (!response.ok || data.status !== 'ok') {
          throw new Error(data.detail || `Backend returned HTTP ${response.status}`)
        }
        setHealth({ status: 'ok', data, error: '' })
      } catch (error) {
        if (!controller.signal.aborted) {
          setHealth({ status: 'error', data: null, error: error.message })
        }
      }
    }

    checkHealth()
    return () => controller.abort()
  }, [retry])

  const statusLabel = {
    checking: 'Connecting',
    ok: 'Operational',
    error: 'Unavailable',
  }[health.status]

  return (
    <main className="workspace">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="Dispute Triage home">
          <span className="wordmark-mark" aria-hidden="true">D</span>
          <span>dispute<span className="wordmark-light">/triage</span></span>
        </a>
        <span className="environment-label"><span /> Local environment</span>
      </header>

      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">OPERATIONS PLATFORM <span> / </span> SYSTEM STATUS</p>
        <h1 id="page-title">It starts<br />with a connection.</h1>
        <p className="intro-copy">Verify that the interface can communicate with the triage API.</p>
      </section>

      <section className={`health-panel health-panel-${health.status}`} aria-labelledby="health-title">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">01 <span> / </span> SERVICES</p>
            <h2 id="health-title">Backend API</h2>
          </div>
          <span className="status-pill" role="status" aria-live="polite">
            <span className="status-dot" />{statusLabel}
          </span>
        </div>

        <div className="service-row">
          <span className="service-icon" aria-hidden="true">↗</span>
          <div className="service-info">
            <strong>{health.data?.service || 'dispute-triage'}</strong>
            <span>GET <code>/health</code></span>
          </div>
          <span className="service-result">{health.status === 'ok' ? '200 OK' : health.status === 'checking' ? '—' : 'ERROR'}</span>
        </div>

        {health.status === 'error' && (
          <p className="error-message" role="alert">Could not connect: {health.error}</p>
        )}

        <footer className="panel-footer">
          <span>{health.status === 'ok' ? 'The frontend and backend are connected.' : health.status === 'checking' ? 'Checking service status…' : 'Make sure the backend is running, then try again.'}</span>
          <button className="retry-button" onClick={() => setRetry((value) => value + 1)} disabled={health.status === 'checking'}>
            <span aria-hidden="true">↻</span> Retry
          </button>
        </footer>
      </section>

      <div className="connection-note">
        <span className="connection-line" aria-hidden="true" />
        <span>Frontend <code>:5173</code></span>
        <span className="connection-arrow" aria-hidden="true">→</span>
        <span>Backend <code>:8000</code></span>
        <span className="connection-route">via Vite proxy</span>
      </div>

      <footer className="page-footer">
        <span>FACTORED HACKATHON 2026</span>
        <span>INTAKE &amp; TRIAGE <span className="footer-separator">/</span> SKELETON</span>
      </footer>
    </main>
  )
}

export default App
