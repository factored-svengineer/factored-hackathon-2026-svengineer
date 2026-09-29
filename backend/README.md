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

- Health: http://localhost:8000/health
- OpenAPI: http://localhost:8000/docs
- Triage stub: `POST /disputes/triage`

```bash
curl -X POST http://localhost:8000/disputes/triage ^
  -H "Content-Type: application/json" ^
  -d "{\"text\": \"No reconozco un cargo de 45.99\"}"
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
