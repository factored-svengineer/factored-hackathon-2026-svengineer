# Data pipeline

Ingestion and validation layer for the Factored Datathon 2026 dispute datasets.

## Priority tables

1. `complaints` — training/eval source via `complaints.description`
2. `transactions` — `is_fraud` / `fraud_score` before decide
3. `customers` — customer context
4. `call_center_interactions` — transcripts for RAG / evidence

## Credentials

AWS credentials are required from environment variables only (see root `.env.example`).
The script loads that file for local development; boto3 is given the access key and
secret explicitly, so it cannot fall back to a shared AWS profile or machine role.

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN` (if temporary credentials)
- `AWS_DEFAULT_REGION`
- `S3_BUCKET`
- `S3_PREFIX` (optional)

Never commit `.env` or hardcode keys — the repository will be public.

## Usage (local)

```bash
cd data-pipeline
pip install -r ../backend/requirements.txt
cp ../.env.example ../.env   # fill in values locally
python -m ingestion.s3_ingest
```

Objects can be stored as files such as `complaints.csv` or `complaints.parquet`,
or as shards under a table folder such as `complaints/part-000.csv`. Supported
formats are CSV, Parquet, JSON, JSONL, and NDJSON (including CSV/Parquet gzip).
Downloaded files are written under `data/raw/<table>/`; the script reports each
table directory after a successful download.

## Validation

`validation/checks.py` defines Pandera contracts for the four priority tables.
`validate_table(name, dataframe)` returns a report with missing columns, null counts,
duplicate rows, and schema failures; `ok` is false when any contract check fails.
Contracts require unique, non-null identifiers; non-null required fields; non-negative
transaction amounts; and fraud scores between 0 and 1. Additional source columns are
currently allowed while the upstream schemas are being confirmed.

To validate downloaded files and shards under `data/raw/`, run this from
`data-pipeline/`; it prints a JSON report and exits non-zero if any table fails:

```bash
python -m validation.checks --data-dir data/raw
```

Install dependencies from the repository root and run the pipeline tests with:

```bash
pip install -r backend/requirements.txt
pytest data-pipeline/tests
```
