# Factored AI & Data Hackathon 2026 — SV Engineer

AI-first **intake and triage of banking transaction disputes** (Spanish / Portuguese).

## Team

| Member | GitHub | Focus |
|--------|--------|-------|
| Daniel | [Daniel73636](https://github.com/Daniel73636) | AI / backend core |
| Juan Tamayo | [JuanTamayoL](https://github.com/JuanTamayoL) | Data pipeline + frontend + eval/deploy |

## What it does

1. Receives a customer dispute in natural language (ES/PT)
2. Extracts structured case facts with Gemini
3. Checks a provided transaction ID against the transaction source (`is_fraud` / `fraud_score`)
4. Decides: auto-resolve · clarify/abstain · escalate to human
5. Verifies the action was actually recorded
6. On escalate: hands off verified facts, actions, evidence, and open questions — never the raw transcript

## Repo layout

```
backend/          FastAPI + state graph + policy + classifier + RAG + tools
frontend/         React + Vite
data-pipeline/    S3 ingestion (boto3 + env) + schema validation
eval/             Held-out cases (ES/PT) + metrics + baseline
docs/             architecture, decisions, limitations
```

## Quick start

```bash
# A local .env starter is included; set GEMINI_API_KEY before using chat.
# Keep real credentials local — .env is gitignored.

# Backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements-api.txt   # API skeleton; use requirements.txt for ML/data
uvicorn app.main:app --reload --port 8000

# Frontend (another terminal)
cd frontend
npm install
npm run dev
```

## Local transaction SQLite index

To build a local SQLite database containing transaction IDs, transaction and
process dates, fraud flags, and fraud scores from the configured S3 bucket, run
from the repository root after installing `backend/requirements.txt`:

```bash
python build_transactions_sqlite.py
```

The script reads `.env` (`S3_BUCKET`, optional `S3_TRANSACTIONS_PREFIX`, and AWS
credentials), streams the CSV objects, and creates `data/transactions.sqlite3`.
It does not replace an existing database unless `--replace` is passed; a rebuild
is published only after all objects load successfully. The transaction ID is a
primary key, so duplicate IDs stop the build rather than silently overriding a
record. The live API uses this database when the file exists and falls back to
S3 only when it is missing. A present but invalid database reports an error
instead of silently switching back to S3. SQLite lookups include the transaction
ID, transaction date, fraud flag, and fraud score; other transaction fields not
stored in this compact index are returned as `null`.

Or with Docker (backend only by default):

```bash
docker compose up --build backend
```

Full stack (adds Vite frontend):

```bash
docker compose --profile full up --build
```
- API: http://localhost:8000/health  
- Docs: http://localhost:8000/docs  
- UI: http://localhost:5173  

## Security

- Credentials **only** via environment variables
- `.env` is gitignored; this repo is expected to be public
- See `docs/limitations.md` for production gaps

## Docs

- [Architecture](docs/architecture.md)
- [Use cases (3 archetypes)](docs/use-cases.md)
- [Human handoff contract](docs/handoff-contract.md)
- [Deterministic policy](docs/policy.md)
- [State graph](docs/graph.md)
- [Ambiguity & abstention](docs/ambiguity.md)
- [Decisions](docs/decisions.md)
- [Limitations](docs/limitations.md)
- [Data pipeline](data-pipeline/README.md)
- [Backend](backend/README.md)
