# Graph nodes (Sprint 2–3)

Pipeline: `understand → decide → act → verify → (escalate)`.

| Node | Behavior |
|------|----------|
| `understand` | Gemini ES/PT extraction + keyword category; txn lookup via S3 (`safe_get_transaction`) |
| `decide` | Deterministic [`evaluate_dispute`](policy.md) + ambiguity abstention |
| `act` | `clarify` → open questions; `auto_resolve`/`escalate` → `safe_create_dispute_case` (retries, typed failures) |
| `verify` | Re-reads case from store; mismatch or missing record → unverified + safe fallback |
| `escalate` | Emits [`HumanHandoff`](handoff-contract.md) v1 |

## Post-action verification & tool fallbacks (Issue #13)

- Tools return `ToolResult` (`app/tools/resilience.py`); success is never claimed on exception.
- Transient errors (`TimeoutError`, `ConnectionError`, `OSError`) retry once.
- Create failure → demote to `escalate`, `verified=false`, record `ActionStatus.FAILED`.
- Verify re-read failure / field mismatch after `auto_resolve` → demote to `escalate`.
- Runner re-checks `decision` after `verify` so demotions still emit handoff.

Classifier is rules-based until issue #10 (baseline ML) lands.
Case persistence is in-memory (`app/tools/store.py`) until a real DB is wired.
