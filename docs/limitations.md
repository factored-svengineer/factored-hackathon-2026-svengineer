# Limitations — what is missing for real production

Status: **hackathon / pre-production** (updated 2026-10-04, Issue #15).

This document lists what the dispute intake & triage system does **not** yet
cover for a real banking deployment. Each gap is grounded in the current code
or in the team's measurements
([`MEDICION_SISTEMA_2026-10-04.txt`](../MEDICION_SISTEMA_2026-10-04.txt),
[`EXTRACCION_EVAL_2026-10-04.txt`](../EXTRACCION_EVAL_2026-10-04.txt)).

The four areas requested in Issue #15 come first: **capacity**, **monitoring**,
**data retention**, and **Portuguese coverage**. Other blocking gaps follow.

## Summary

| Area | Today | Main gap | Priority |
|------|-------|----------|----------|
| [Capacity](#1-capacity-and-performance) | In-memory case store; SQLite or S3 CSV scan for lookups; single uvicorn process | No persistent DB, no timeouts, no rate limits, no load test | P0 |
| [Monitoring](#2-monitoring-and-observability) | `/health`, `execution_trace`, JSON logs, CI | No metrics, alerts, dashboards, or durable audit store | P1 |
| [Data retention](#3-data-retention-and-privacy) | Handoff and traces forbid raw transcripts | Case store keeps raw customer text; no TTL/deletion; PII in logs | P0 |
| [Portuguese coverage](#4-portuguese-coverage) | ES/PT/EN prompts and UI; 3 PT eval fixtures | Tiny PT sample; no PT corpus for classifier/RAG | P1 |
| [Decision safety](#5-decision-safety-ownership-check) | Deterministic policy + human approval gate | No complaint↔transaction `customer_id` ownership check | P0 |
| [Security](#6-security-authn--authz) | CORS allow-list, input validation | No authentication or authorization | P0 |
| [Model / eval risk](#7-model-and-evaluation-risk) | Small fixture evals at 100% | Sample far too small; classifier not wired into the graph | P1 |
| [Deploy](#8-deployment-and-operations) | Docker / docker-compose for local use | No cloud deploy, secrets manager, or runbook (Issue #18) | P1 |

P0 = must fix before handling real customers. P1 = needed for a reliable pilot.

---

## 1. Capacity and performance

**What exists**

- Case persistence is a Python `dict` behind a `threading.Lock`
  (`backend/app/tools/store.py`). It is process-local and lost on restart.
- Transaction lookup (`backend/app/tools/aws_data.py`) uses a read-only local
  SQLite index (`data/transactions.sqlite3`, built with
  `build_transactions_sqlite.py`) when present. Otherwise it **streams CSV
  partitions from S3** and, if the date partition misses, scans the whole
  prefix — roughly **0.75 GiB** per unlucky lookup. S3 Select is not allowed by
  the bucket policy.
- Gemini extraction (`backend/app/graph/google_extractor.py`) retries up to 3
  times with backoff on 5xx/unavailable and maps quota errors to HTTP 429.
- Measured local latency of `understand()+decide()` with SQLite: p50 0.03 ms,
  p95 0.79 ms (180 runs). This **excludes** HTTP, Gemini, S3, case writes, and
  approval wait, so it says nothing about end-to-end latency.

**What is missing**

- **Persistent, shared case store.** Multiple workers or instances would each
  hold different cases. `DATABASE_URL` / `SUPABASE_*` exist in `.env.example`
  but no code uses them.
- **Timeouts.** Gemini calls have no request timeout; S3 reads have none
  either. A slow provider blocks the request thread. During our demo a live
  HTTP triage with an unknown transaction ID hung on the S3 scan.
- **Concurrency settings.** `backend/Dockerfile` runs a single uvicorn process
  (no `--workers`); routes are synchronous and Gemini/S3 calls block.
- **Rate limiting and quotas** per client/customer. Gemini free-tier limits
  (~15 requests/minute in our tests) would be hit quickly under real traffic.
- **Caching / connection reuse.** A new `boto3` S3 client is created per lookup;
  no lookup cache.
- **Pagination.** `list_dispute_cases()` returns everything.
- **Load and soak testing**, capacity targets (requests/s, p95), and
  autoscaling rules.
- The SQLite index is a local file snapshot: no refresh schedule, no
  consistency guarantees with the source data.

**Next steps:** move cases to Postgres (Supabase/Neon, Issue #18); serve
transaction lookups from an indexed table instead of S3 scans; add timeouts and
circuit breakers on Gemini/S3; run uvicorn/gunicorn with multiple workers; add
rate limiting; run a load test and set SLOs.

## 2. Monitoring and observability

**What exists**

- `GET /health` liveness probe, used by the docker-compose healthcheck.
- Per-run auditable `execution_trace` with `trace_id`, node steps, roles
  (`llm_extraction` / `business_rules` / `tool` / `system`) and rule reasons
  (`backend/app/graph/tracing.py`, Issue #14). Emitted as JSON log lines on the
  `app.graph.trace` logger and returned by `/disputes/triage`.
- GitHub Actions CI runs ruff + pytest (backend) and the Vite build (frontend).

**What is missing**

- **Durable trace / audit storage.** Traces live only in the HTTP response and
  stdout logs; nothing stores them for later review or regulator export.
- **Logging configuration.** No central log config (level, format, sink);
  output depends on uvicorn defaults.
- **Metrics:** request rate, latency percentiles, error rate, Gemini quota/429
  rate, S3 lookup duration, decision mix (auto_resolve / clarify / escalate),
  approval accept/reject rate, fallback count (`tool_failures`,
  `fallback_applied`).
- **Alerting** on error spikes, Gemini quota exhaustion, verify failures, or a
  jump in escalations.
- **Readiness checks** for dependencies (Gemini key valid, SQLite/S3
  reachable); `/health` only reports that the process is up.
- **Distributed tracing** (e.g. OpenTelemetry) across frontend → API → Gemini/S3.
- **Cost telemetry.** Per-case cost was not estimated; our evaluations used
  0 paid requests (local) or 12 Gemini calls (extraction eval).

**Next steps:** persist `execution_trace` per case; add structured logging
config; export Prometheus/OpenTelemetry metrics; define alerts; add a
dependency-aware readiness endpoint.

## 3. Data retention and privacy

**What exists**

- The `HumanHandoff` contract forbids raw transcripts and dialogue
  (`backend/app/contracts/handoff.py`); `GET /contracts/human-handoff` lists
  forbidden fields.
- Execution traces never log customer text (only `has_text: true/false`) or
  chain-of-thought.
- Secrets come only from environment variables; `.env`, `*.sqlite3`,
  `data/raw/`, and `data/processed/` are gitignored.
- The frontend keeps chat state in memory only (no `localStorage`).

**What is missing**

- **Raw customer text is stored with the case.** `act()` passes
  `"text": state.get("text")` into `create_dispute_case`
  (`backend/app/graph/nodes.py`), so the full free-text dispute sits in the
  case store. Production needs minimization (store extracted facts only) or a
  separate, access-controlled, encrypted store.
- **Retention policy.** No TTL, archival, or deletion for cases, traces,
  logs, or the transaction SQLite snapshot. No customer deletion/right-to-erasure
  endpoint. `clear_dispute_cases()` is a test helper only.
- **PII in logs.** Trace steps include `customer_id`, `transaction_id`,
  amounts, and fraud scores. These need masking or a restricted log sink.
- **Third-party processing.** Customer text is sent to Google AI Studio for
  extraction. A real bank needs a DPA, data-residency review, and a decision on
  whether a paid/enterprise endpoint with no training on inputs is required.
- **Encryption at rest** for cases and the local transaction index; access
  controls and audit of who read which case.
- A documented **data classification** (PII, financial, fraud signals) and
  legal retention periods per country (ES/PT-speaking markets differ).

**Next steps:** stop persisting raw text (or encrypt + isolate it); define
retention periods and a deletion job; mask PII in logs; formalize the Gemini
data-processing terms.

## 4. Portuguese coverage

**What exists**

- Language-aware behavior for `es`, `pt`, and `en`: heuristic language
  detection (`backend/app/graph/extract.py`), Gemini prompt/schema
  (`google_extractor.py`), ambiguity messages (`ambiguity.py`), clarification
  and escalation prompts (`nodes.py`), create-failure message (`verify_ops.py`).
- The chat UI is translated into EN/ES/PT (`frontend/src/App.jsx`).
- `eval/cases` has **6 fixtures: 3 ES + 3 PT**, one per archetype
  (clear fraud, ambiguous, human required).
- Extraction eval (12 texts, ES/PT originals + paraphrases): Gemini reached
  100% precision/recall on amount, currency, and transaction ID; the regex
  baseline dropped to 50% recall on amount/currency when amounts were written in
  words.

**What is missing**

- **Sample size.** PT evidence is 3 fixtures (plus 6 PT texts in the extraction
  eval). ES/PT pairs are translations of the same 3 archetypes, so the
  independent evidence is 3 scenarios, not 6. The 100% figures cannot be
  projected to production.
- **Backend tests in PT:** only about 2 tests exercise Portuguese
  (`test_extract_entities_pt`, one ambiguity API test).
- **PT data for ML components.** The baseline classifier and RAG retriever are
  only tested on English toy data; there is no PT (or ES) complaints corpus or
  policy corpus indexed.
- **Regional variants:** pt-BR vs pt-PT vocabulary, currency (BRL vs EUR),
  date and number formats (`1.234,56`) are not systematically tested.
- **Language mixing** (ES/PT "portuñol", code-switching) and language detection
  without a hint were not measured; the extraction eval passed `language_hint`.
- **Human review of PT copy.** Prompts and UI strings were not reviewed by a
  native Portuguese speaker or compliance team.

**Next steps:** build a held-out PT set of at least a few hundred real or
realistic disputes (pt-BR and pt-PT); add PT regression tests per node; run the
extraction and decision evals per language and report them separately; native
review of all customer-facing PT text.

## 5. Decision safety: ownership check

This gap was found by the system measurement and is **P0**.

- In the clear-fraud fixtures the transaction's `customer_id` differs from the
  complaint's `customer_id`, yet the policy still proposed `auto_resolve`
  (2/2 rows, 1 independent pair).
- `understand()` fills `customer_id` from the transaction when the complaint has
  none, and nothing compares the two when both exist. The `customer_id_mismatch`
  check in `verify_ops.py` only compares the created case against graph state,
  not complaint against transaction.
- The human approval gate (`require_approval=True` on `/disputes/triage`)
  stopped execution in the measurement, but no human approver decision was
  measured, so the gate's effectiveness is unknown.

**Next step:** add a deterministic rule in `decide` — if complaint and
transaction `customer_id` differ (or the customer is unauthenticated), never
`auto_resolve`; escalate with reason `ownership_mismatch`.

## 6. Security (AuthN / AuthZ)

- **No authentication or authorization** on any endpoint. Anyone who can reach
  the API can submit disputes, look up transactions by ID, and approve actions.
- No binding between the chat user and a bank customer identity, which also
  makes the ownership check above impossible to enforce properly.
- CORS uses an allow-list from `CORS_ORIGINS`, but falls back to `["*"]` when
  the variable is empty, with `allow_credentials=True`.
- Input validation exists for `text` and the `TRX-` + 20-character transaction
  ID format; no request size limits or abuse protection.
- No secrets manager; credentials are plain environment variables.

## 7. Model and evaluation risk

- Both evaluations report 100% decision accuracy on 6 and 12 examples. These
  numbers describe the fixtures only.
- The baseline TF-IDF classifier (`backend/app/classifier/baseline.py`,
  `eval/baseline.py`) is tested on English toy data and is **not called** by the
  triage graph; escalations default the category to `unknown`.
- The RAG retriever (`backend/app/rag/retriever.py`) is implemented and tested
  but **not wired** into the graph or API. FAISS is mentioned in docs but not
  implemented.
- `eval/cases` fixtures are not run by any automated eval job; results live in
  manual text reports.
- The `fraud_score` thresholds (`backend/app/policy/rules.py`) are hand-set and
  not calibrated against labeled outcomes.

## 8. Deployment and operations

- Only local Docker / docker-compose exist. Cloud deployment (Vercel frontend,
  Render backend, Supabase/Neon DB) is planned in Issue #18 but not implemented.
- No environment separation (dev/staging/prod), no migrations, no backup and
  restore, no rollback procedure, no on-call runbook.
- CI does not deploy, scan dependencies, or run security checks.

## Already in place (not gaps)

To avoid confusion with earlier versions of this file:

- **Tool reliability:** post-action verification and safe fallbacks are
  implemented (Issue #13): `ToolResult` with retries, re-read of the created
  case, demotion to `escalate` on create/verify failure, never claiming success.
- **Explainability:** execution traces based on records and rules, with Gemini
  limited to extraction (Issue #14).
- **Human approval** before `auto_resolve` or `escalate` is executed, in the
  runner and the chat UI.

## Prioritized roadmap

1. **P0** — Ownership rule (`customer_id` mismatch → never auto-resolve).
2. **P0** — Authentication and customer identity binding.
3. **P0** — Persistent case DB; stop storing raw customer text; retention and
   deletion policy.
4. **P0** — Timeouts on Gemini and S3; replace S3 scans with an indexed lookup.
5. **P1** — Metrics, alerts, durable trace storage.
6. **P1** — PT (pt-BR/pt-PT) held-out set and per-language eval reports.
7. **P1** — Cloud deploy with secrets management (Issue #18).
8. **P2** — Wire classifier/RAG into the graph after they beat the baseline on
   real held-out data.
