import { useEffect, useRef, useState } from 'react'
import './App.css'

const welcomeMessage = {
  role: 'assistant',
  content: 'To review your disputed transaction without guessing, please provide:\n- Amount and currency\n- Transaction date\n- Merchant or beneficiary\n- Transaction ID, or the merchant and date if you do not have the ID\n\nPlease do not include full card numbers or passwords.',
}

function App() {
  const [health, setHealth] = useState({ status: 'checking', data: null, error: '' })
  const [retry, setRetry] = useState(0)
  const [messages, setMessages] = useState([welcomeMessage])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [caseResult, setCaseResult] = useState(null)
  const feedRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()

    async function checkHealth() {
      setHealth({ status: 'checking', data: null, error: '' })
      try {
        const response = await fetch('/api/health', { signal: controller.signal })
        const data = await response.json().catch(() => ({}))
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

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  async function sendMessage(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || loading) return
    const conversationText = [
      ...messages.filter((message) => message.role === 'user').map((message) => message.content),
      text,
    ].join('\n')
    const wasAskedForVerification = caseResult?.state?.open_questions?.some(
      (question) => question.field === 'verification_evidence',
    )
    const verificationEvidenceUnavailable = wasAskedForVerification &&
      /^(?:no\b|i\s+(?:cannot|can['’]?t|am unable to|do not have|don['’]?t have)\b)/i.test(text)

    setMessages((current) => [...current, { role: 'user', content: text }])
    setDraft('')
    setLoading(true)

    try {
      const response = await fetch('/api/disputes/triage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: conversationText,
          language: 'en',
          verification_evidence_unavailable: verificationEvidenceUnavailable,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data.detail || `Backend returned HTTP ${response.status}`)
      }

      const state = data.state || {}
      const verified = state.verified === true
      const status = data.decision === 'auto_resolve' && verified
        ? 'resolved'
        : data.decision === 'escalate' && verified
          ? 'escalated'
          : 'pending'
      const reply = status === 'resolved'
        ? 'The case was resolved and its outcome was verified.'
        : status === 'escalated'
          ? 'This case needs a human agent. The verified handoff context is available in the case panel.'
          : (data.clarification_prompts || []).join(' ') || 'The case is pending more information before it can be safely resolved.'

      setCaseResult({ ...data, status })
      setMessages((current) => [...current, { role: 'assistant', content: reply }])
    } catch (error) {
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: `I could not process this case: ${error.message}`, error: true },
      ])
    } finally {
      setLoading(false)
    }
  }

  function startNewCase() {
    setMessages([welcomeMessage])
    setCaseResult(null)
    setDraft('')
  }

  const status = caseResult?.status || 'pending'
  const caseClosed = status === 'resolved' || status === 'escalated'
  const handoff = caseResult?.state?.handoff
  const verifiedTransaction = handoff?.verified_transaction
  const statusLabel = health.status === 'ok' ? 'API connected' : health.status === 'checking' ? 'Connecting' : 'API unavailable'
  const formatValue = (value) => value === null || value === undefined || value === '' ? 'Not provided' : String(value)

  return (
    <main className="workspace">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="Dispute Triage home">
          <span className="wordmark-mark" aria-hidden="true">D</span>
          <span>dispute<span className="wordmark-light">/triage</span></span>
        </a>
        <div className="topbar-actions">
          <span className={`environment-label environment-${health.status}`} role="status">
            <span />{statusLabel}
          </span>
          <button className="new-case-button" onClick={startNewCase}>＋ New case</button>
        </div>
      </header>

      <section className="workspace-heading" aria-labelledby="page-title">
        <div>
          <p className="eyebrow">CUSTOMER OPERATIONS <span>/</span> DISPUTE INTAKE</p>
          <h1 id="page-title">Case workspace</h1>
          <p className="intro-copy">Review a dispute and its verified routing outcome.</p>
        </div>
        <div className={`case-status case-status-${status}`} role="status" aria-live="polite">
          <span className="status-dot" />
          <span><small>CASE STATUS</small>{status[0].toUpperCase() + status.slice(1)}</span>
        </div>
      </section>

      {health.status === 'error' && (
        <div className="connection-warning" role="alert">
          <span>Could not reach the triage API: {health.error}</span>
          <button className="text-button" onClick={() => setRetry((value) => value + 1)}>Retry connection</button>
        </div>
      )}

      <section className="case-layout" aria-label="Dispute case workspace">
        <section className="chat-panel" aria-labelledby="chat-title">
          <div className="section-heading chat-heading">
            <div>
              <p className="eyebrow">01 <span>/</span> CONVERSATION</p>
              <h2 id="chat-title">Customer chat</h2>
            </div>
            <span className="conversation-state"><span /> {loading ? 'Reviewing' : 'Ready'}</span>
          </div>

          <div className="message-feed" ref={feedRef} aria-live="polite">
            {messages.map((message, index) => (
              <article className={`message message-${message.role}${message.error ? ' message-error' : ''}`} key={`${index}-${message.role}`}>
                <span className="message-avatar" aria-hidden="true">{message.role === 'user' ? 'Y' : 'D'}</span>
                <div className="message-body">
                  <span className="message-label">{message.role === 'user' ? 'You' : 'Triage assistant'}</span>
                  <p>{message.content}</p>
                </div>
              </article>
            ))}
            {loading && (
              <div className="typing-indicator" role="status"><span /><span /><span /> Reviewing case details</div>
            )}
          </div>

          <form className="composer" onSubmit={sendMessage}>
            <label className="visually-hidden" htmlFor="message-input">Describe the dispute</label>
            <textarea
              id="message-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  sendMessage(event)
                }
              }}
              placeholder="Describe the disputed transaction..."
              rows="2"
              disabled={loading || caseClosed}
            />
            <div className="composer-footer">
              <span>Enter to send · Shift + Enter for a new line</span>
              <button className="send-button" type="submit" aria-label="Send message" disabled={loading || caseClosed || !draft.trim()}>
                <span aria-hidden="true">↑</span>
              </button>
            </div>
          </form>
        </section>

        <aside className="context-panel" aria-labelledby="context-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">02 <span>/</span> HUMAN ROUTING</p>
              <h2 id="context-title">Verified handoff</h2>
            </div>
            {handoff && <span className="handoff-mark" aria-label="Handoff created">↗</span>}
          </div>

          {handoff ? (
            <div className="handoff-content">
              <div className="handoff-id"><span>HANDOFF ID</span><strong>{handoff.handoff_id}</strong></div>
              <p className="handoff-reason">{handoff.reason}</p>

              <section className="context-section">
                <h3>Case details</h3>
                <dl className="detail-list">
                  <div><dt>Case ID</dt><dd>{formatValue(handoff.case?.complaint_id)}</dd></div>
                  <div><dt>Category</dt><dd>{formatValue(handoff.classified_category?.category)}{handoff.classified_category?.subcategory ? ` · ${handoff.classified_category.subcategory}` : ''}</dd></div>
                  <div><dt>Priority</dt><dd>{formatValue(handoff.case?.priority)}</dd></div>
                  <div><dt>SLA breached</dt><dd>{handoff.case?.sla_breached === true ? 'Yes' : handoff.case?.sla_breached === false ? 'No' : 'Not provided'}</dd></div>
                </dl>
              </section>

              <section className="context-section">
                <h3>Verified transaction</h3>
                {verifiedTransaction ? (
                  <dl className="detail-list">
                    <div><dt>Transaction</dt><dd>{formatValue(verifiedTransaction.transaction_id)}</dd></div>
                    <div><dt>Merchant</dt><dd>{formatValue(verifiedTransaction.merchant_name)}</dd></div>
                    <div><dt>Amount</dt><dd>{formatValue(verifiedTransaction.amount)} {verifiedTransaction.currency || ''}</dd></div>
                    <div><dt>Source</dt><dd>{formatValue(verifiedTransaction.verification_source)}</dd></div>
                    <div><dt>Verified at</dt><dd>{formatValue(verifiedTransaction.verified_at)}</dd></div>
                  </dl>
                ) : (
                  <p className="empty-note">No transaction was verified before handoff.</p>
                )}
              </section>

              {handoff.support_evidence?.length > 0 && (
                <section className="context-section">
                  <h3>Support evidence</h3>
                  <ul className="evidence-list">
                    {handoff.support_evidence.map((item) => <li key={item.evidence_id}>{item.summary}</li>)}
                  </ul>
                </section>
              )}

              {handoff.open_questions?.length > 0 && (
                <section className="context-section">
                  <h3>Open questions</h3>
                  <ul className="evidence-list">
                    {handoff.open_questions.map((item) => <li key={item.question_id}>{item.prompt}</li>)}
                  </ul>
                </section>
              )}
              <p className="privacy-note">Only structured case facts and summaries are included. Raw chat transcripts are excluded.</p>
            </div>
          ) : caseResult?.status === 'resolved' ? (
            <div className="resolved-outcome" role="status" aria-live="polite">
              <span className="resolved-outcome-icon" aria-hidden="true">✓</span>
              <strong>Case resolved automatically</strong>
              <p>The transaction was verified and the dispute outcome was recorded.</p>
            </div>
          ) : (
            <div className="empty-handoff">
              <span className="empty-handoff-icon" aria-hidden="true">↗</span>
              <strong>{caseResult?.status === 'resolved' ? 'No agent handoff needed' : 'No handoff created'}</strong>
              <p>{caseResult?.status === 'resolved' ? 'The case was resolved automatically.' : 'Verified context will appear here if the case is escalated to a human agent.'}</p>
            </div>
          )}
        </aside>
      </section>

      <footer className="page-footer">
        <span>FACTORED HACKATHON 2026</span>
        <span>INTAKE &amp; TRIAGE <span className="footer-separator">/</span> CASE REVIEW</span>
      </footer>
    </main>
  )
}

export default App
