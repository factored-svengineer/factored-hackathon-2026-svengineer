# Architecture — Dispute Intake & Triage

## Goal

AI-first intake and triage of banking transaction disputes (ES/PT):

1. Accept a natural-language dispute from the customer
2. Classify dispute category/subcategory (ML vs baseline on `complaints.description`)
3. Verify the disputed transaction against `is_fraud` / `fraud_score`
4. Decide: auto-resolve, clarify/abstain, or escalate to a human
5. Verify that the chosen action was actually recorded
6. On escalation, hand off verified facts — never the raw transcript

## Components

| Layer | Stack | Role |
|-------|-------|------|
| Backend | FastAPI + explicit state graph | understand → decide → act → verify → escalate |
| Policy | Deterministic Python rules | amount / priority / SLA thresholds |
| Classifier | Baseline (TF-IDF+LR) vs proposed (embeddings/LLM) | category/subcategory |
| RAG | Chroma/FAISS | transcripts + dispute policies |
| Data | DuckDB over S3 | complaints, transactions, customers, call_center_interactions |
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
   [understand]  extract entities, classify category
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
