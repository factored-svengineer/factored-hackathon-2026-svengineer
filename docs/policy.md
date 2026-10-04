# Deterministic policy layer

Business thresholds (amount, priority, SLA, fraud score) live in
`backend/app/policy/rules.py` — **never** in LLM prompts.

## Decisions

| Decision | When |
|----------|------|
| `escalate` | Critical/High priority, `sla_breached`, status Escalated, amount ≥ escalate threshold, or SLA hours nearly exhausted |
| `clarify` | Missing amount / transaction ref, or ambiguous fraud score without `is_fraud` |
| `auto_resolve` | `is_fraud` and normalized `fraud_score ≥ 0.85`, facts present, **and** no escalate signal |

Precedence is safe-by-default: **escalate > clarify > auto_resolve**.

## Fraud score

Datathon `transactions.fraud_score` is typically **0–100**.
`normalize_fraud_score()` maps values `> 1` to `[0, 1]` via `/100`.

## API

- `GET /policy/config` — active thresholds (env-overridable)
- `POST /policy/evaluate` — decision + machine-readable `reasons`

Env overrides: `POLICY_HIGH_AMOUNT_USD`, `POLICY_ESCALATE_AMOUNT_USD`,
`POLICY_FRAUD_AUTO_RESOLVE`, `POLICY_FRAUD_AMBIGUOUS_LOW`,
`POLICY_FRAUD_AMBIGUOUS_HIGH`, `POLICY_SLA_HOURS_HIGH_PRIORITY`,
`POLICY_SLA_HOURS_DEFAULT`.

## Graph wiring

The `decide` node calls `evaluate_dispute(...)` and stores `policy_evaluation`
on the state. Issue #14 promotes those reasons into `execution_trace` steps
(`role=business_rules`). Gemini never participates in this decision.
