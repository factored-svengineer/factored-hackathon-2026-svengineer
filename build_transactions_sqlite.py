"""Build a local SQLite index from the transaction CSV objects in S3."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import math
import os
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import boto3
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "data" / "transactions.sqlite3"
REQUIRED_COLUMNS = {
    "transaction_id",
    "transaction_date",
    "process_date",
    "customer_id",
    "amount",
    "currency",
    "amount_usd",
    "merchant_name",
    "transaction_status",
    "is_fraud",
    "fraud_score",
}
INSERT_BATCH_SIZE = 1_000


def _s3_client() -> Any:
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
    session_token = os.getenv("AWS_SESSION_TOKEN", "").strip()
    if bool(access_key) != bool(secret_key):
        raise ValueError(
            "Configure both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
            "or use an AWS role/default credential provider."
        )
    if session_token and not access_key:
        raise ValueError(
            "AWS_SESSION_TOKEN requires AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY."
        )

    options: dict[str, Any] = {
        "region_name": os.getenv("AWS_DEFAULT_REGION", "us-east-1").strip(),
    }
    if access_key:
        options.update(
            {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "aws_session_token": session_token or None,
            }
        )
    return boto3.client("s3", **options)


def _object_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    keys = [
        item["Key"]
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix
        )
        for item in page.get("Contents", [])
        if item["Key"].lower().endswith((".csv", ".csv.gz"))
    ]
    return sorted(keys)


def _csv_text_stream(body: BinaryIO, compressed: bool) -> TextIO:
    binary_stream = gzip.GzipFile(fileobj=body) if compressed else body
    return io.TextIOWrapper(binary_stream, encoding="utf-8-sig", newline="")


def _optional_value(value: str | None) -> str | None:
    normalized = value.strip() if value is not None else ""
    return normalized or None


def _parse_bool(value: str | None, key: str, row_number: int) -> int | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"true", "1"}:
        return 1
    if normalized in {"false", "0"}:
        return 0
    raise ValueError(f"{key}: invalid is_fraud value at CSV row {row_number}.")


def _parse_score(value: str | None, key: str, row_number: int) -> float | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    try:
        score = float(normalized)
    except ValueError as exc:
        raise ValueError(
            f"{key}: invalid fraud_score value at CSV row {row_number}."
        ) from exc
    if not math.isfinite(score):
        raise ValueError(f"{key}: non-finite fraud_score at CSV row {row_number}.")
    return score


def _parse_number(
    value: str | None, column: str, key: str, row_number: int
) -> float | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    try:
        number = float(normalized)
    except ValueError as exc:
        raise ValueError(
            f"{key}: invalid {column} value at CSV row {row_number}."
        ) from exc
    if not math.isfinite(number):
        raise ValueError(
            f"{key}: non-finite {column} value at CSV row {row_number}."
        )
    return number


def _read_object(client: Any, bucket: str, key: str) -> Iterator[tuple[Any, ...]]:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        text_stream = _csv_text_stream(body, key.lower().endswith(".csv.gz"))
        try:
            reader = csv.DictReader(text_stream)
            if not reader.fieldnames:
                raise ValueError(f"{key}: CSV has no header.")

            header_map = {
                header.strip().lower(): header
                for header in reader.fieldnames
                if header is not None
            }
            missing_columns = REQUIRED_COLUMNS - header_map.keys()
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise ValueError(f"{key}: missing required CSV columns: {missing}.")

            for row_number, row in enumerate(reader, start=2):
                normalized = {
                    name: row.get(original_name)
                    for name, original_name in header_map.items()
                }
                transaction_id = _optional_value(normalized.get("transaction_id"))
                if transaction_id is None:
                    raise ValueError(
                        f"{key}: empty transaction_id at CSV row {row_number}."
                    )
                yield (
                    transaction_id,
                    _optional_value(normalized.get("transaction_date")),
                    _optional_value(normalized.get("process_date")),
                    _optional_value(normalized.get("customer_id")),
                    _parse_number(normalized.get("amount"), "amount", key, row_number),
                    _optional_value(normalized.get("currency")),
                    _parse_number(
                        normalized.get("amount_usd"), "amount_usd", key, row_number
                    ),
                    _optional_value(normalized.get("merchant_name")),
                    _optional_value(normalized.get("transaction_status")),
                    _parse_bool(normalized.get("is_fraud"), key, row_number),
                    _parse_score(normalized.get("fraud_score"), key, row_number),
                )
        finally:
            text_stream.close()
    finally:
        body.close()


def _insert_batch(
    connection: sqlite3.Connection, key: str, batch: list[tuple[Any, ...]]
) -> None:
    try:
        connection.executemany(
            """
            INSERT INTO transactions (
                transaction_id, transaction_date, process_date, customer_id,
                amount, currency, amount_usd, merchant_name, transaction_status,
                is_fraud, fraud_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            f"{key}: duplicate transaction_id encountered; "
            "the SQLite database was not published."
        ) from exc


def build_database(database_path: Path, replace_existing: bool) -> tuple[int, int]:
    bucket = os.getenv("S3_BUCKET", "").strip()
    if not bucket:
        raise ValueError("S3_BUCKET must be configured.")
    prefix = os.getenv("S3_TRANSACTIONS_PREFIX", "data/transactions/").strip("/")
    prefix = f"{prefix or 'data/transactions'}/"

    if database_path.exists() and not replace_existing:
        raise FileExistsError(
            f"{database_path} already exists. Choose another --db path or use --replace."
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{database_path.name}.",
        suffix=".tmp",
        dir=database_path.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    connection: sqlite3.Connection | None = None
    try:
        client = _s3_client()
        keys = _object_keys(client, bucket, prefix)
        if not keys:
            raise FileNotFoundError(
                f"No transaction CSV objects found under s3://{bucket}/{prefix}"
            )

        connection = sqlite3.connect(temporary_path)
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(
            """
            CREATE TABLE transactions (
                transaction_id TEXT NOT NULL PRIMARY KEY,
                transaction_date TEXT,
                process_date TEXT,
                customer_id TEXT,
                amount REAL,
                currency TEXT,
                amount_usd REAL,
                merchant_name TEXT,
                transaction_status TEXT,
                is_fraud INTEGER CHECK (is_fraud IN (0, 1) OR is_fraud IS NULL),
                fraud_score REAL
            )
            """
        )

        total_rows = 0
        with connection:
            for key in keys:
                batch = []
                for record in _read_object(client, bucket, key):
                    batch.append(record)
                    total_rows += 1
                    if len(batch) >= INSERT_BATCH_SIZE:
                        _insert_batch(connection, key, batch)
                        batch.clear()
                if batch:
                    _insert_batch(connection, key, batch)

        connection.close()
        connection = None
        os.replace(temporary_path, database_path)
        return len(keys), total_rows
    finally:
        if connection is not None:
            connection.close()
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description=(
            "Stream transaction CSVs from S3 into a local SQLite database "
            "indexed by transaction_id."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"SQLite output path (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing database only after a successful rebuild.",
    )
    args = parser.parse_args()

    try:
        object_count, row_count = build_database(args.db.expanduser(), args.replace)
    except Exception as exc:
        print(f"Could not build transaction database: {exc}", file=sys.stderr)
        return 1

    size_bytes = args.db.expanduser().stat().st_size
    print(
        f"Created {args.db.expanduser()} from {object_count} S3 objects "
        f"({row_count:,} transactions; {size_bytes:,} bytes)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
