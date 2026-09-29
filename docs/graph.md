# Graph nodes (Sprint 2)

Pipeline: `understand → decide → act → verify → (escalate)`.

| Node | Behavior |
|------|----------|
| `understand` | Heuristic ES/PT extraction (amount, currency, date, merchant, txn id) + keyword category; optional txn lookup from `data/raw` |
| `decide` | Deterministic [`evaluate_dispute`](policy.md) only |
| `act` | `clarify` → open questions; `auto_resolve`/`escalate` → persist case in local store |
| `verify` | Re-reads case / confirms clarification prompts exist |
| `escalate` | Emits [`HumanHandoff`](handoff-contract.md) v1 |

Classifier is rules-based until issue #10 (baseline ML) lands.
Case persistence is in-memory (`app/tools/store.py`) until a real DB is wired.
