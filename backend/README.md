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
