"""Download priority tables from the Factored Datathon S3 bucket.

Credentials MUST come from environment variables (.env locally; never hardcoded).
Priority tables: complaints, transactions, customers, call_center_interactions.
"""

from __future__ import annotations

import os
from pathlib import Path

import boto3


PRIORITY_TABLES = (
    "complaints",
    "transactions",
    "customers",
    "call_center_interactions",
)


def _s3_client():
    # Credentials resolved by boto3 from env / shared config — never hardcode.
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def ingest_table(table_name: str, dest_dir: str | Path) -> Path:
    """Download a single table prefix/object from S3 into dest_dir."""
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ.get("S3_PREFIX", "")
    key = f"{prefix}{table_name}" if prefix else table_name

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / f"{table_name}.parquet"

    client = _s3_client()
    # Placeholder: adjust key/extension once exact S3 layout is known.
    client.download_file(bucket, key, str(out_path))
    return out_path


def ingest_priority_tables(dest_dir: str | Path = "data/raw") -> dict[str, Path]:
    """Ingest the four priority tables used by the dispute triage system."""
    return {name: ingest_table(name, dest_dir) for name in PRIORITY_TABLES}


if __name__ == "__main__":
    paths = ingest_priority_tables()
    for name, path in paths.items():
        print(f"{name} -> {path}")
