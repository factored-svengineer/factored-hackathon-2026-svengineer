import { useEffect, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function App() {
  const [health, setHealth] = useState({ status: 'checking', detail: null })

  useEffect(() => {
    let cancelled = false
    fetch(`${API_URL}/health`)
      .then(async (res) => {
        const data = await res.json()
        if (!cancelled) {
          setHealth({
            status: res.ok ? 'ok' : 'error',
            detail: data,
          })
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setHealth({ status: 'error', detail: { message: err.message } })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui', maxWidth: 640, margin: '3rem auto', padding: '0 1rem' }}>
      <h1>Dispute Intake & Triage</h1>
      <p>Factored Hackathon 2026 — end-to-end skeleton (frontend ↔ backend health).</p>
      <section>
        <h2>Backend health</h2>
        <p>
          Status:{' '}
          <strong style={{ color: health.status === 'ok' ? 'green' : health.status === 'checking' ? 'gray' : 'crimson' }}>
            {health.status}
          </strong>
        </p>
        <pre style={{ background: '#f4f4f4', padding: '1rem', overflow: 'auto' }}>
          {JSON.stringify(health.detail, null, 2)}
        </pre>
        <p style={{ fontSize: '0.875rem', color: '#555' }}>API: {API_URL}</p>
      </section>
    </main>
  )
}

export default App
