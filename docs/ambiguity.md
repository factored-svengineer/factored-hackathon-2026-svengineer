# Ambiguity & abstention (Issue #9)

When amount, date, merchant, or fraud signals are missing/unclear, the graph
**must not invent facts** to force `auto_resolve`.

## Modes

| Mode | Meaning |
|------|---------|
| `clarify` | Ask the customer for missing fields (monto, fecha, comercio, txn id) |
| `abstain` | Refuse automatic resolution (e.g. grey-zone fraud) without guessing |

Implementation: `backend/app/graph/ambiguity.py` → attached on `decide` as
`state.ambiguity` / `state.abstention`. The API surfaces it on
`POST /disputes/triage` (`abstained`, `abstention`, `clarification_prompts`).

## Forbidden inventions

Never fabricate: `amount`, `currency`, `transaction_date`, `merchant_name`,
`transaction_id`, `is_fraud`, `fraud_score`.

## Precedence with policy

1. Escalate signals still win (Critical / SLA / high amount)
2. Else if ambiguous → clarify/abstain (blocks auto_resolve)
3. Else clear fraud + complete facts → auto_resolve
