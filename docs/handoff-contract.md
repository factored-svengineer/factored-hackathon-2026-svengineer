# Human handoff contract (v1.0.0)

Canonical JSON package delivered when the graph decides **escalate**.
Consumers: **frontend** (agent UI), **data-pipeline** (export/audit), **eval**.

Source of truth in code: `backend/app/contracts/handoff.py`  
Live endpoints:

- `GET /contracts/human-handoff` — schema + example + forbidden fields
- `GET /contracts/human-handoff/example` — typed example only
- Static copy: `docs/schemas/human-handoff.schema.json`

## Guarantees

| Rule | Detail |
|------|--------|
| No raw transcript | Never include `full_text` / dialogue turns. Use `support_evidence[].summary` |
| Fraud score normalized | `fraud_score` ∈ **[0, 1]**; optional `fraud_score_raw` keeps dataset scale (0–100) |
| Extra fields forbidden | Pydantic `extra="forbid"` — unknown keys are rejected |
| Versioned | `schema_version` (semver). Bump on breaking changes |

## Top-level shape

```json
{
  "schema_version": "1.0.0",
  "handoff_id": "HO-…",
  "created_at": "2025-10-29T02:00:00Z",
  "reason": "priority=Critical AND sla_breached=true",
  "case": { "...": "CaseContext" },
  "verified_transaction": { "...": "VerifiedTransaction | null" },
  "classified_category": { "...": "ClassifiedCategory" },
  "fraud_score": 0.0,
  "actions_taken": [],
  "open_questions": [],
  "support_evidence": []
}
```

### Required conceptual fields (issue #3)

| Field | Purpose |
|-------|---------|
| `verified_transaction` | Facts confirmed against transactions (or `null` if unknown) |
| `classified_category` | Category / subcategory (+ confidence, classifier) |
| `fraud_score` | Normalized score for UI / policy (0–1) |
| `actions_taken` | What the system already did (with status + optional `verification_ref`) |
| `open_questions` | What the human still needs to resolve |
| `support_evidence` | Short factual summaries (policy, complaint fields, transcript **summary**) |

## Example (human-required archetype)

Grounded in `CMP-W9KJLENI8RSM8TU99NXZ` — see `build_example_handoff()` and
[use-cases.md](use-cases.md).

## Frontend / data-pipeline usage

1. Fetch `GET /contracts/human-handoff` at build time or startup, **or**
2. Commit/consume `docs/schemas/human-handoff.schema.json`
3. Validate payloads with the schema before rendering or exporting
4. Reject any payload that includes forbidden transcript fields

## Out of scope

- Raw chat / call transcripts
- LLM chain-of-thought
- Full customer PII dumps beyond ids needed to work the case
