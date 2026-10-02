# Backend — Dispute Intake & Triage

FastAPI skeleton with an explicit state-graph runner
(`understand → decide → act → verify → escalate`). Node bodies are stubs;
this package is meant to run locally so Sprint 2 work can plug in.

## Run without Docker

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements-api.txt
uvicorn app.main:app --reload --port 8000
```

The repository-root `.env` is loaded automatically. Replace
`PASTE_YOUR_GOOGLE_AI_STUDIO_API_KEY_HERE` with a real Gemini API key from
Google AI Studio before sending a chat message. The placeholder lets the
service start, but triage requests return HTTP 503 until a real key is set.
`GEMINI_MODEL` selects the extraction model. Gemini extracts only transaction
facts; business decisions remain in the deterministic policy layer.
Transient Gemini service errors (HTTP 500/502/503/504) are retried up to three
times with a short exponential delay. Invalid credentials, unavailable model
names, quota exhaustion, and invalid responses are not retried.
Quota exhaustion is returned as HTTP 429; transient provider failures that
remain after retries are returned as HTTP 502.

When Gemini extracts a transaction ID, the backend lists daily CSV objects
under the configured `S3_BUCKET` and streams their contents directly from S3;
it does not persist or download the dataset to local files. The default
`S3_TRANSACTIONS_PREFIX` is `data/transactions/`, with partitions in
`year=YYYY/month=MM/day=DD/`. Set it in the root `.env` only if the bucket
layout changes. `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` may be used
without a session token for long-lived credentials; AWS role/default
credentials are also supported.

A supplied transaction date's partition is searched first. If the ID is not
there, other partitions are scanned to account for late arrivals. The current
read-only bucket policy does not permit S3 Select, so an ID-only lookup can
read up to the entire 0.75 GiB transaction dataset over the network. No files
are stored locally, but this fallback can be slow. Missing S3 configuration
returns HTTP 503; S3 read/list failures return HTTP 502.

For ML/data work (DuckDB, sklearn, Chroma, Pandera, etc.):

```bash
pip install -r requirements.txt
```

## Classification and retrieval

`BaselineClassifier` trains TF-IDF + logistic regression on complaint descriptions.
Labels should combine category and subcategory, for example
`Transactions | Unrecognized charge`; `predict_proba()` returns probabilities
per label. For held-out evaluation, `eval/baseline.py` exposes
`train_baseline(texts, labels)` and `evaluate_baseline(model, texts, labels)` from
the repository root. The `complaints.description` field is often a template, so
metrics may not represent performance on natural-language text.

`DisputeRetriever.index(documents, metadatas)` accepts passages from transcripts
and policies; metadata fields such as `source` and `document_id` are recommended.
`retrieve(query, k)` returns ranked passages with metadata and similarity scores.
It uses Chroma when installed and local TF-IDF as a fallback, without downloading
models.

- Health: http://localhost:8000/health
- OpenAPI: http://localhost:8000/docs
- Human handoff contract: http://localhost:8000/contracts/human-handoff
- Triage stub: `POST /disputes/triage`

```bash
curl -X POST http://localhost:8000/disputes/triage ^
  -H "Content-Type: application/json" ^
  -d "{\"text\": \"I do not recognize a charge of 45.99\"}"
```

## Run with Docker Compose

From the repo root (backend only — default):

```bash
docker compose up --build backend
```

Full stack (backend + frontend):

```bash
docker compose --profile full up --build
```

## Tests

```bash
cd backend
pytest -q
```

## Layout

```
app/
  main.py          # FastAPI app
  api/routes.py    # /health, /graph/nodes, /disputes/triage
  graph/           # nodes + runner (stubs → Sprint 2)
  policy/          # deterministic rules
  classifier/      # baseline + proposed
  rag/             # retrieval stubs
  tools/           # data access stubs
```
