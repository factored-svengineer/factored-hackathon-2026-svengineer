"""Download priority tables from the Factored Datathon S3 bucket.

Credentials MUST come from environment variables (.env locally; never hardcoded).
Priority tables: complaints, transactions, customers, call_center_interactions.
"""

from __future__ import annotations

import os
from pathlib import Path
from pathlib import PurePosixPath

import boto3
from dotenv import load_dotenv


load_dotenv()


PRIORITY_TABLES = (
    "complaints",
    "transactions",
    "customers",
    "call_center_interactions",
)


def _s3_client():
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise EnvironmentError(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in the environment"
        )

    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def _table_objects(client, bucket: str, prefix: str, table_name: str) -> list[str]:
    table_prefix = f"{prefix}{table_name}/"
    supported_suffixes = (".csv", ".parquet", ".json", ".jsonl", ".ndjson", ".csv.gz", ".parquet.gz")
    keys: list[str] = []

    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    ):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.endswith("/"):
                continue

            relative = key[len(prefix):] if prefix else key
            relative_path = PurePosixPath(relative)
            parts = relative_path.parts
            if not parts or relative_path.is_absolute() or any(
                part in (".", "..") or "\\" in part for part in parts
            ):
                continue

            in_table_directory = relative.startswith(table_prefix[len(prefix):])
            is_table_file = (
                len(parts) == 1
                and (parts[0] == table_name or parts[0].startswith(f"{table_name}."))
            )
            if in_table_directory or is_table_file:
                name = parts[-1].lower()
                if name == table_name or name.endswith(supported_suffixes):
                    keys.append(key)

    return sorted(keys)


def ingest_table(table_name: str, dest_dir: str | Path) -> Path:
    """Download all data objects for one table into a local table directory."""
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise EnvironmentError("S3_BUCKET must be set in the environment")

    prefix = os.environ.get("S3_PREFIX", "").strip("/")
    prefix = f"{prefix}/" if prefix else ""
    client = _s3_client()
    keys = _table_objects(client, bucket, prefix, table_name)
    if not keys:
        raise FileNotFoundError(
            f"No supported S3 data objects found for '{table_name}' "
            f"in s3://{bucket}/{prefix}"
        )

    table_dir = Path(dest_dir) / table_name
    table_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        relative = key[len(prefix):] if prefix else key
        parts = PurePosixPath(relative).parts
        if parts[0] == table_name and len(parts) > 1:
            parts = parts[1:]
        local_relative = Path(*parts)
        out_path = table_dir / local_relative
        out_path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(out_path))

    return table_dir


def ingest_priority_tables(dest_dir: str | Path = "data/raw") -> dict[str, Path]:
    """Ingest the four priority tables used by the dispute triage system."""
    return {name: ingest_table(name, dest_dir) for name in PRIORITY_TABLES}


if __name__ == "__main__":
    paths = ingest_priority_tables()
    for name, path in paths.items():
        print(f"{name} -> {path}")
