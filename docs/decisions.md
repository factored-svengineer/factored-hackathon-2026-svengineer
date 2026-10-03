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

## ADR-007 — Explicit abstention on ambiguous disputes

- **Status:** Accepted (Issue #9)
- **Context:** Missing amount/date/merchant or grey-zone fraud must not be
  filled by the LLM to force a resolution.
- **Decision:** `assess_ambiguity()` produces clarify/abstain with
  `forbidden_inventions`; `decide` demotes `auto_resolve` → `clarify` when
  ambiguous. API returns `abstention` + prompts.
- **Consequences:** Safer triage; more clarify cases until facts are supplied.

## ADR-008 — Gemini for entity extraction, deterministic policy for decisions

- **Status:** Accepted
- **Context:** Free-form customer messages need broader extraction than fixed
  regular expressions provide, while business decisions must remain auditable.
- **Decision:** Use Google AI Studio structured output only in the `understand`
  node to extract explicitly stated transaction facts. Keep classification and
  business policy deterministic; never silently fall back to regex when the
  provider is unavailable.
- **Consequences:** Triage requires a valid `GEMINI_API_KEY`; ambiguous or
  absent values remain unset and are handled by the existing clarification
  policy.

## ADR-009 — Post-action verify + safe tool fallbacks

- **Status:** Accepted (Issue #13)
- **Context:** Claiming a dispute case was registered when the write or re-read
  failed would mislead customers and agents.
- **Decision:** Wrap side-effect tools in `ToolResult` with limited retries;
  `verify` re-reads the case; on create/verify failure demote to `escalate`
  with `verified=false` and never report success.
- **Consequences:** More escalations under infrastructure faults; auditable
  `tool_failures` / `fallback_applied` on the graph state.
