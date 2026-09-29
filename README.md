# Factored AI & Data Hackathon 2026 — SV Engineer

AI-first **intake and triage of banking transaction disputes** (Spanish / Portuguese).

## Team

| Member | GitHub | Focus |
|--------|--------|-------|
| Daniel | [Daniel73636](https://github.com/Daniel73636) | AI / backend core |
| Juan Tamayo | [JuanTamayoL](https://github.com/JuanTamayoL) | Data pipeline + frontend + eval/deploy |

## What it does

1. Receives a customer dispute in natural language (ES/PT)
2. Classifies dispute category/subcategory (baseline vs proposed model on `complaints.description`)
3. Checks the disputed transaction (`is_fraud` / `fraud_score`)
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
cp .env.example .env   # fill AWS_* and S3_BUCKET locally — never commit .env

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
