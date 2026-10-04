# Architecture — Dispute Intake & Triage

## Goal

AI-first intake and triage of banking transaction disputes (ES/PT):

1. Accept a natural-language dispute from the customer
2. Extract structured transaction facts with Gemini
3. If an ID is present, verify the transaction against `is_fraud` / `fraud_score`
4. Decide: auto-resolve, clarify/abstain, or escalate to a human
5. Ask the customer for permission before auto-resolving or escalating
6. Verify that an approved action was actually recorded
7. On escalation, hand off verified facts — never the raw transcript

## Components

| Layer | Stack | Role |
|-------|-------|------|
| Backend | FastAPI + explicit state graph | understand → decide → act → verify → escalate |
| Policy | Deterministic Python rules | amount / priority / SLA thresholds |
| Extraction | Google AI Studio (Gemini structured output) | transaction facts from customer text |
| RAG | Chroma/FAISS | transcripts + dispute policies |
| Data | Read-only S3 access | stream daily transaction CSV partitions for ID lookup |
| Frontend | React + Vite | chat UI + case status + human handoff view |
| Eval | Held-out ES/PT cases | normal / ambiguous / human-required |

## Decision flow

Concrete archetypes (real `complaints` / `transactions` IDs) live in
[use-cases.md](use-cases.md): clear fraud → `auto_resolve`, incomplete info →
`clarify`, critical/SLA → `escalate`.

```
Customer NL dispute (ES/PT)
        │
        ▼
   [understand]  Gemini extracts entities; a provided transaction ID is looked up
        │
        ▼
   [decide]  policy + fraud_score → auto | clarify | escalate
        │
        ▼
   [act]  create case / ask clarification / prepare escalate
        │
        ▼
   [verify]  confirm persistence / tool success
        │
        ├── ok → done
        └── escalate path → [escalate] structured handoff
```

## Human handoff contract

Finalized in [handoff-contract.md](handoff-contract.md) (`schema_version` **1.0.0**).

- Code: `backend/app/contracts/handoff.py`
- JSON Schema: [schemas/human-handoff.schema.json](schemas/human-handoff.schema.json)
- Example: [schemas/human-handoff.example.json](schemas/human-handoff.example.json)
- API: `GET /contracts/human-handoff`

Never includes raw transcripts — only verified facts, actions, evidence summaries, and open questions.

Gemini is used only for extracting explicitly stated entities. Deterministic
policy code remains responsible for all business decisions. If Google AI Studio
is not configured or returns an error, the triage endpoint surfaces an error
instead of silently switching to regex extraction.

The live transaction lookup uses `data/transactions.sqlite3` when that local
database exists. It queries by the indexed `transaction_id` and returns the
stored dates, customer, amount, currency, merchant, status, fraud flag, and
fraud score. When a transaction ID is supplied, these verified values fill
fields the customer did not provide. A transaction marked `Denied` is not
auto-resolved as a refund; the flow clarifies that no completed charge is
available to refund and requests evidence if the customer sees a posted charge.
An ID that is not found in available records, or cannot be looked up, is
immediately escalated for human review. Without an ID, the policy evaluates the
extracted facts and asks for missing information when the facts are
insufficient; the chat path does not re-classify the original text locally.
If the SQLite file is absent, the lookup falls back to streaming CSV objects from
`S3_TRANSACTIONS_PREFIX` (default `data/transactions/`): it searches the
provided date partition first, then other partitions because `process_date` can
differ from `transaction_date` for late arrivals. S3 Select is not permitted by
the current bucket policy, so this fallback can read the full 0.75 GiB dataset.
