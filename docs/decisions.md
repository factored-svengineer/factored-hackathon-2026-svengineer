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

## ADR-006 — Deterministic policy layer owns triage thresholds

- **Status:** Accepted (Issue #8)
- **Context:** LLMs must not invent amount / priority / SLA / fraud cutoffs.
- **Decision:** Centralize rules in `backend/app/policy/rules.py` with
  `evaluate_dispute()` returning `auto_resolve | clarify | escalate` plus
  explicit `reasons`. Normalize datathon fraud scores (0–100 → 0–1). Wire the
  graph `decide` node exclusively through this API.
- **Consequences:** Threshold changes require code/env review; explainability
  comes from `reasons`, not model CoT.
