# Graph nodes (Sprint 2–3)

Pipeline: `understand → decide → act → verify → (escalate)`.

| Node | Behavior |
|------|----------|
| `understand` | Gemini structured extraction + transaction ID lookup (`safe_get_transaction`) |
| `decide` | Deterministic [`evaluate_dispute`](policy.md) + ambiguity abstention |
| `act` | `clarify` → open questions; `auto_resolve`/`escalate` → `safe_create_dispute_case` (retries, typed failures) |
| `verify` | Re-reads case from store; mismatch or missing record → unverified + safe fallback |
| `escalate` | Emits [`HumanHandoff`](handoff-contract.md) v1 |

## Execution tracing / explainability (Issue #14)

Each run produces `execution_trace` (+ `trace_id`) on graph state and the triage API:

- Steps record **facts**, **machine-readable reasons**, and **roles**
  (`llm_extraction` | `business_rules` | `tool` | `system`).
- **Gemini only extracts stated entities.** It never chooses
  `auto_resolve` / `clarify` / `escalate`.
- The `decide` step always has `roles: ["business_rules"]` and policy/ambiguity
  reasons — no chain-of-thought.
- Structured logs: logger `app.graph.trace` emits JSON
  `dispute_execution_trace` / `dispute_execution_step`.
- Contract: `GET /graph/trace-contract`.

## Post-action verification & tool fallbacks (Issue #13)

- Tools return `ToolResult` (`app/tools/resilience.py`); success is never claimed on exception.
- Transient errors (`TimeoutError`, `ConnectionError`, `OSError`) retry once.
- Create failure → demote to `escalate`, `verified=false`, record `ActionStatus.FAILED`.
- Verify re-read failure / field mismatch after `auto_resolve` → demote to `escalate`.
- Runner re-checks `decision` after `verify` so demotions still emit handoff.

The chat triage path does not classify dispute categories from the raw message.
Resolution uses extracted facts, transaction lookup results, and deterministic
policy rules. A supplied transaction ID that is absent from available records
or cannot be looked up is escalated for human review.
When clarification requires a transaction ID, the chat presents localized yes/no
choices. Selecting yes opens an ID-only input; selecting no records that answer
and escalates the existing case to a human without repeating Gemini extraction.
IDs follow the sampled database format `TRX-` plus 20 uppercase alphanumeric
characters. Submitting a valid ID uses the structured API field and bypasses
Gemini extraction.
Automatic resolution and escalation pause after the decision node until the
customer approves the proposed action. Declining closes the chat case without
creating or resolving a dispute. Ambiguous cases continue through clarification
without requesting consent until a final action is proposed.
Case persistence is in-memory (`app/tools/store.py`) until a real DB is wired.
