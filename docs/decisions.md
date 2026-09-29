# Decision log

Record architectural and product decisions here (ADR-lite).

## ADR-001 — Explicit state graph over free-form agent loops

- **Status:** Accepted
- **Context:** Dispute triage must be auditable for regulators and humans.
- **Decision:** Use an explicit graph (`understand → decide → act → verify → escalate`) instead of an unconstrained ReAct loop.
- **Consequences:** Easier tracing, clearer ownership of nodes, slightly more boilerplate.

## ADR-002 — Business policy as deterministic code

- **Status:** Accepted
- **Context:** Amount thresholds, priority, and SLA must not be invented by an LLM.
- **Decision:** Keep policy in `backend/app/policy/`; LLM may propose, policy decides.
- **Consequences:** Safe defaults; policy changes require code review.

## ADR-003 — Credentials only from environment

- **Status:** Accepted
- **Context:** Repo will be public; S3 holds sensitive datathon data.
- **Decision:** `.env` gitignored; `.env.example` documents names only.
- **Consequences:** Local onboarding requires copying secrets out-of-band.

## ADR-004 — Three dispute archetypes from real complaints sample

- **Status:** Accepted (Issue #1)
- **Context:** Need concrete paths for the state graph before implementing nodes.
- **Decision:** Define clear-fraud / ambiguous / human-required using real
  `complaint_id`s (and a high-`fraud_score` txn for verification). Treat
  `complaints.description` as a weak template; use structured fields + optional
  transcripts for NL. Normalize `fraud_score` from 0–100 to 0–1 in policy.
- **Consequences:** Eval cases and graph design share the same anchors
  (`docs/use-cases.md`, `eval/cases`).
