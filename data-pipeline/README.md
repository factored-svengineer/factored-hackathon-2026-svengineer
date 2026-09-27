# Data pipeline

Ingestion and validation layer for the Factored Datathon 2026 dispute datasets.

## Priority tables

1. `complaints` — training/eval source via `complaints.description`
2. `transactions` — `is_fraud` / `fraud_score` before decide
3. `customers` — customer context
4. `call_center_interactions` — transcripts for RAG / evidence

## Credentials

Read **only** from environment variables (see root `.env.example`):

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN` (if temporary credentials)
- `AWS_DEFAULT_REGION`
- `S3_BUCKET`
- `S3_PREFIX` (optional)

Never commit `.env` or hardcode keys — the repository will be public.

## Usage (local)

```bash
cp ../.env.example ../.env   # fill in values locally
python -m ingestion.s3_ingest
```

## Validation

`validation/checks.py` runs null / duplicate / schema checks.
Extend with Pandera or Great Expectations as the contracts stabilize.
