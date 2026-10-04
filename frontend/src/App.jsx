import { useEffect, useRef, useState } from 'react'
import './App.css'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')

const chatCopy = {
  en: {
    welcome: 'To review your disputed transaction without guessing, please provide:\n- Amount and currency\n- Transaction date\n- Merchant or beneficiary\n- Transaction ID, or the merchant and date if you do not have the ID\n\nPlease do not include full card numbers or passwords.',
    resolved: 'The case was resolved and its outcome was verified.',
    escalated: 'This case needs a human agent. The verified handoff context is available in the case panel.',
    pending: 'The case is pending more information before it can be safely resolved.',
    error: 'I could not process this case:',
    haveTransactionId: 'Do you have the transaction ID?',
    yesHaveId: 'Yes, I have the transaction ID',
    noHaveId: 'No, I do not have the transaction ID',
    yesUserMessage: 'Yes, I have the transaction ID.',
    noUserMessage: 'No, I do not have the transaction ID.',
    transactionIdPlaceholder: 'Enter only the transaction ID',
    transactionIdSuffixPlaceholder: '20 letters or numbers',
    submitTransactionId: 'Submit ID',
    autoApprovalPrompt: 'This case is eligible for an automatic refund. Would you like us to proceed?',
    humanApprovalPrompt: 'This case cannot be resolved automatically. Would you like us to send it to a human agent for review?',
    approveAuto: 'Yes, proceed with the refund',
    approveHuman: 'Yes, send it to an agent',
    rejectAndClose: 'No, close this case',
    approvalAcceptedAuto: 'Yes, proceed with the automatic refund.',
    approvalAcceptedHuman: 'Yes, send my case to a human agent.',
    approvalDeclined: 'No, close my case without resolving it.',
    declined: 'This case was closed without being resolved. Start a new case if you need more help.',
    awaitingApproval: 'Awaiting approval',
  },
  es: {
    welcome: 'Para revisar la transacción disputada sin hacer suposiciones, proporcione:\n- Monto y moneda\n- Fecha de la transacción\n- Comercio o beneficiario\n- ID de la transacción, o el comercio y la fecha si no tiene el ID\n\nNo incluya números completos de tarjeta ni contraseñas.',
    resolved: 'El caso se resolvió y el resultado fue verificado.',
    escalated: 'Este caso requiere atención de un agente. El contexto verificado está disponible en el panel del caso.',
    pending: 'El caso necesita más información antes de poder resolverse de forma segura.',
    error: 'No pude procesar este caso:',
    haveTransactionId: '¿Tienes el ID de la transacción?',
    yesHaveId: 'Sí, tengo el ID de la transacción',
    noHaveId: 'No, no tengo el ID de la transacción',
    yesUserMessage: 'Sí, tengo el ID de la transacción.',
    noUserMessage: 'No, no tengo el ID de la transacción.',
    transactionIdPlaceholder: 'Escribe únicamente el ID de la transacción',
    transactionIdSuffixPlaceholder: '20 letras o números',
    submitTransactionId: 'Enviar ID',
    autoApprovalPrompt: 'Este caso puede recibir un reembolso automático. ¿Deseas continuar?',
    humanApprovalPrompt: 'Este caso no se puede resolver automáticamente. ¿Deseas enviarlo a un agente para que lo revise?',
    approveAuto: 'Sí, continuar con el reembolso',
    approveHuman: 'Sí, enviarlo a un agente',
    rejectAndClose: 'No, cerrar este caso',
    approvalAcceptedAuto: 'Sí, continuar con el reembolso automático.',
    approvalAcceptedHuman: 'Sí, enviar mi caso a un agente.',
    approvalDeclined: 'No, cerrar mi caso sin resolverlo.',
    declined: 'Este caso se cerró sin resolverse. Inicia un caso nuevo si necesitas más ayuda.',
    awaitingApproval: 'Esperando aprobación',
  },
  pt: {
    welcome: 'Para analisar a transação contestada sem fazer suposições, informe:\n- Valor e moeda\n- Data da transação\n- Estabelecimento ou beneficiário\n- ID da transação, ou o estabelecimento e a data caso não tenha o ID\n\nNão inclua números completos de cartão nem senhas.',
    resolved: 'O caso foi resolvido e o resultado foi verificado.',
    escalated: 'Este caso precisa de atendimento humano. O contexto verificado está disponível no painel do caso.',
    pending: 'O caso precisa de mais informações antes de poder ser resolvido com segurança.',
    error: 'Não foi possível processar este caso:',
    haveTransactionId: 'Você tem o ID da transação?',
    yesHaveId: 'Sim, tenho o ID da transação',
    noHaveId: 'Não, não tenho o ID da transação',
    yesUserMessage: 'Sim, tenho o ID da transação.',
    noUserMessage: 'Não, não tenho o ID da transação.',
    transactionIdPlaceholder: 'Digite somente o ID da transação',
    transactionIdSuffixPlaceholder: '20 letras ou números',
    submitTransactionId: 'Enviar ID',
    autoApprovalPrompt: 'Este caso é elegível para reembolso automático. Deseja continuar?',
    humanApprovalPrompt: 'Este caso não pode ser resolvido automaticamente. Deseja enviá-lo para análise de um agente humano?',
    approveAuto: 'Sim, continuar com o reembolso',
    approveHuman: 'Sim, enviar para um agente',
    rejectAndClose: 'Não, fechar este caso',
    approvalAcceptedAuto: 'Sim, continuar com o reembolso automático.',
    approvalAcceptedHuman: 'Sim, enviar meu caso para um agente humano.',
    approvalDeclined: 'Não, fechar meu caso sem resolvê-lo.',
    declined: 'Este caso foi fechado sem ser resolvido. Inicie um novo caso se precisar de ajuda.',
    awaitingApproval: 'Aguardando aprovação',
  },
}

const supportedLanguages = ['en', 'es', 'pt']
const getChatCopy = (language) => chatCopy[supportedLanguages.includes(language) ? language : 'en']
const createWelcomeMessage = (language) => ({ role: 'assistant', content: getChatCopy(language).welcome })

function App() {
  const [health, setHealth] = useState({ status: 'checking', data: null, error: '' })
  const [retry, setRetry] = useState(0)
  const [responseLanguage, setResponseLanguage] = useState('auto')
  const [messages, setMessages] = useState([createWelcomeMessage('en')])
  const [draft, setDraft] = useState('')
  const [transactionIdDraft, setTransactionIdDraft] = useState('')
  const [transactionIdChoice, setTransactionIdChoice] = useState(null)
  const [loading, setLoading] = useState(false)
  const [caseResult, setCaseResult] = useState(null)
  const feedRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()

    async function checkHealth() {
      setHealth({ status: 'checking', data: null, error: '' })
      try {
        const response = await fetch(`${API_BASE_URL}/health`, { signal: controller.signal })
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

  async function submitMessage(event, {
    text,
    requestText = text,
    transactionIdUnavailable = false,
    structuredTransactionId = null,
    approvalGranted = false,
    approvalDecision = null,
    approvalResponse = false,
  }) {
    event?.preventDefault()
    if (!text || loading) return
    const requestedLanguage = responseLanguage === 'auto'
      ? caseResult?.state?.language || null
      : responseLanguage
    const conversationParts = [
      ...messages
        .filter((message) => message.role === 'user' && !message.approvalResponse)
        .map((message) => message.content),
      requestText,
    ].filter(Boolean)
    const conversationText = conversationParts.join('\n')
    const wasAskedForVerification = caseResult?.state?.open_questions?.some(
      (question) => question.field === 'verification_evidence',
    )
    const verificationEvidenceUnavailable = wasAskedForVerification &&
      /^(?:no\b|i\s+(?:cannot|can['’]?t|am unable to|do not have|don['’]?t have)\b)/i.test(text)

    setMessages((current) => [...current, {
      role: 'user',
      content: text,
      approvalResponse,
    }])
    setDraft('')
    setTransactionIdDraft('')
    setLoading(true)

    try {
      const response = await fetch(`${API_BASE_URL}/disputes/triage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: conversationText,
          language: requestedLanguage,
          verification_evidence_unavailable: verificationEvidenceUnavailable
            || (approvalGranted && caseResult?.state?.verification_evidence_unavailable === true),
          transaction_id_unavailable: transactionIdUnavailable
            || (approvalGranted && caseResult?.state?.transaction_id_unavailable === true),
          transaction_id: approvalGranted
            ? caseResult?.state?.transaction_id || null
            : structuredTransactionId,
          require_approval: true,
          approval_granted: approvalGranted,
          approval_decision: approvalDecision,
          amount: transactionIdUnavailable || approvalGranted ? caseResult?.state?.amount : null,
          currency: transactionIdUnavailable || approvalGranted ? caseResult?.state?.currency : null,
          merchant_name: transactionIdUnavailable || approvalGranted ? caseResult?.state?.merchant_name : null,
          transaction_date: transactionIdUnavailable || approvalGranted ? caseResult?.state?.transaction_date : null,
          customer_id: transactionIdUnavailable || approvalGranted ? caseResult?.state?.customer_id : null,
          is_fraud: approvalGranted ? caseResult?.state?.is_fraud : null,
          fraud_score: approvalGranted ? caseResult?.state?.fraud_score : null,
          priority: approvalGranted ? caseResult?.state?.priority : null,
          sla_breached: approvalGranted ? caseResult?.state?.sla_breached : null,
          status: approvalGranted ? caseResult?.state?.status : null,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data.detail || `Backend returned HTTP ${response.status}`)
      }

      const state = data.state || {}
      const verified = state.verified === true
      const awaitingApproval = state.approval_required === true
      const status = awaitingApproval
        ? 'awaiting_approval'
        : data.decision === 'auto_resolve' && verified
        ? 'resolved'
        : data.decision === 'escalate' && verified
          ? 'escalated'
          : 'pending'
      const language = state.language || requestedLanguage || 'en'
      const copy = getChatCopy(language)
      const reply = awaitingApproval
        ? data.decision === 'auto_resolve'
          ? copy.autoApprovalPrompt
          : copy.humanApprovalPrompt
        : status === 'resolved'
        ? copy.resolved
        : status === 'escalated'
          ? copy.escalated
          : (data.clarification_prompts || []).join(' ') || copy.pending

      setCaseResult({ ...data, status })
      if (responseLanguage === 'auto' && supportedLanguages.includes(state.language)) {
        setMessages((current) => current.map((message, index) => (
          index === 0 ? createWelcomeMessage(state.language) : message
        )))
      }
      setMessages((current) => [...current, { role: 'assistant', content: reply }])
    } catch (error) {
      const copy = getChatCopy(activeLanguage)
      if (transactionIdUnavailable) setTransactionIdChoice(null)
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: `${copy.error} ${error.message}`, error: true },
      ])
    } finally {
      setLoading(false)
    }
  }

  function sendMessage(event) {
    submitMessage(event, { text: draft.trim() })
  }

  function chooseTransactionIdAvailability(hasId) {
    const copy = getChatCopy(responseLanguage === 'auto'
      ? caseResult?.state?.language
      : responseLanguage)
    setTransactionIdChoice(hasId ? 'yes' : 'no')
    setTransactionIdDraft('')
    if (!hasId) {
      submitMessage(null, {
        text: copy.noUserMessage,
        transactionIdUnavailable: true,
      })
      return
    }
    setMessages((current) => [...current, { role: 'user', content: copy.yesUserMessage }])
  }

  function sendTransactionId(event) {
    const suffix = transactionIdDraft.trim().toUpperCase()
    if (!/^[A-Z0-9]{20}$/.test(suffix)) return
    const transactionId = `TRX-${suffix}`
    const requestText = activeLanguage === 'es'
      ? `ID de transacción: ${transactionId}`
      : activeLanguage === 'pt'
        ? `ID da transação: ${transactionId}`
        : `Transaction ID: ${transactionId}`
    submitMessage(event, {
      text: transactionId,
      requestText,
      structuredTransactionId: transactionId,
    })
    setTransactionIdChoice(null)
  }

  function respondToApproval(approved) {
    const language = activeLanguage
    const copy = getChatCopy(language)
    const decision = caseResult?.decision
    if (!approved) {
      setMessages((current) => [...current, {
        role: 'user',
        content: copy.approvalDeclined,
        approvalResponse: true,
      }, {
        role: 'assistant',
        content: copy.declined,
      }])
      setCaseResult((current) => ({ ...current, status: 'declined', approval_required: false }))
      return
    }
    submitMessage(null, {
      text: decision === 'auto_resolve' ? copy.approvalAcceptedAuto : copy.approvalAcceptedHuman,
      requestText: '',
      approvalGranted: true,
      approvalDecision: decision,
      approvalResponse: true,
    })
  }

  function startNewCase() {
    setMessages([createWelcomeMessage(responseLanguage === 'auto' ? 'en' : responseLanguage)])
    setCaseResult(null)
    setDraft('')
    setTransactionIdDraft('')
    setTransactionIdChoice(null)
  }

  const status = caseResult?.status || 'pending'
  const caseClosed = status === 'resolved' || status === 'escalated' || status === 'declined'
  const askedForTransactionId = caseResult?.state?.open_questions?.some(
    (question) => question.field === 'transaction_id',
  )
  const activeLanguage = responseLanguage === 'auto'
    ? caseResult?.state?.language || 'en'
    : responseLanguage
  const activeCopy = getChatCopy(activeLanguage)
  const caseStatusText = status === 'awaiting_approval'
    ? activeCopy.awaitingApproval
    : status === 'declined'
      ? activeLanguage === 'es' ? 'Cerrado' : activeLanguage === 'pt' ? 'Fechado' : 'Declined'
      : status[0].toUpperCase() + status.slice(1)
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
          <span><small>CASE STATUS</small>{caseStatusText}</span>
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

          {status === 'awaiting_approval' ? (
            <div className="composer approval-composer">
              <div className="id-choice-buttons">
                <button
                  type="button"
                  onClick={() => respondToApproval(true)}
                  disabled={loading}
                >
                  {caseResult.decision === 'auto_resolve'
                    ? activeCopy.approveAuto
                    : activeCopy.approveHuman}
                </button>
                <button
                  type="button"
                  onClick={() => respondToApproval(false)}
                  disabled={loading}
                >
                  {activeCopy.rejectAndClose}
                </button>
              </div>
            </div>
          ) : askedForTransactionId && transactionIdChoice !== 'yes' ? (
            <div className="composer id-choice-composer">
              <strong>{activeCopy.haveTransactionId}</strong>
              <div className="id-choice-buttons">
                <button
                  type="button"
                  onClick={() => chooseTransactionIdAvailability(true)}
                  disabled={loading || caseClosed}
                >
                  {activeCopy.yesHaveId}
                </button>
                <button
                  type="button"
                  onClick={() => chooseTransactionIdAvailability(false)}
                  disabled={loading || caseClosed}
                >
                  {activeCopy.noHaveId}
                </button>
              </div>
            </div>
          ) : askedForTransactionId ? (
            <form className="composer" onSubmit={sendTransactionId}>
              <label className="visually-hidden" htmlFor="transaction-id-input">
                {activeCopy.transactionIdPlaceholder}
              </label>
              <span className="transaction-id-prefix" aria-hidden="true">TRX-</span>
              <input
                id="transaction-id-input"
                type="text"
                autoComplete="off"
                inputMode="text"
                maxLength={20}
                value={transactionIdDraft}
                onChange={(event) => setTransactionIdDraft(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    sendTransactionId(event)
                  }
                }}
                placeholder={activeCopy.transactionIdSuffixPlaceholder}
                disabled={loading || caseClosed}
              />
              <div className="composer-footer">
                <div className="composer-options">
                  <label htmlFor="response-language">Response language</label>
                  <select
                    id="response-language"
                    value={responseLanguage}
                    onChange={(event) => setResponseLanguage(event.target.value)}
                    disabled={loading || caseClosed}
                  >
                    <option value="auto">Auto-detect</option>
                    <option value="en">English</option>
                    <option value="es">Español</option>
                    <option value="pt">Português</option>
                  </select>
                </div>
                <button className="send-button" type="submit" aria-label={activeCopy.submitTransactionId} disabled={loading || caseClosed || !/^[A-Z0-9]{20}$/.test(transactionIdDraft)}>
                  <span aria-hidden="true">↑</span>
                </button>
              </div>
            </form>
          ) : (
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
                <div className="composer-options">
                  <label htmlFor="response-language">Response language</label>
                  <select
                    id="response-language"
                    value={responseLanguage}
                    onChange={(event) => {
                      const language = event.target.value
                      setResponseLanguage(language)
                      if (!messages.some((message) => message.role === 'user')) {
                        setMessages([createWelcomeMessage(language === 'auto' ? 'en' : language)])
                      }
                    }}
                    disabled={loading || caseClosed}
                  >
                    <option value="auto">Auto-detect</option>
                    <option value="en">English</option>
                    <option value="es">Español</option>
                    <option value="pt">Português</option>
                  </select>
                  <span>Enter to send · Shift + Enter for a new line</span>
                </div>
                <button className="send-button" type="submit" aria-label="Send message" disabled={loading || caseClosed || !draft.trim()}>
                  <span aria-hidden="true">↑</span>
                </button>
              </div>
            </form>
          )}
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
