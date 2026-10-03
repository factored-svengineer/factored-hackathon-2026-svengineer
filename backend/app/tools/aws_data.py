"""Streaming transaction lookups directly from read-only S3 objects."""

from __future__ import annotations

import codecs
import csv
import gzip
import logging
import os
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
SQLITE_DATABASE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "transactions.sqlite3"
)


class S3ConfigurationError(RuntimeError):
    """Raised when the read-only S3 connection is not configured."""


class S3LookupError(RuntimeError):
    """Raised when S3 cannot complete a transaction lookup."""


def _transactions_prefix() -> str:
    prefix = os.getenv("S3_TRANSACTIONS_PREFIX", "data/transactions/").strip("/")
    if not prefix:
        prefix = "data/transactions"
    return f"{prefix}/"


def _date_partition_prefix(transactions_prefix: str, transaction_date: str) -> str | None:
    try:
        parsed = date.fromisoformat(transaction_date[:10])
    except (TypeError, ValueError):
        return None
    return (
        f"{transactions_prefix}year={parsed.year:04d}/"
        f"month={parsed.month:02d}/day={parsed.day:02d}/"
    )


def _text_lines(stream: Any, compressed: bool) -> Iterable[str]:
    binary_stream = gzip.GzipFile(fileobj=stream) if compressed else stream
    lines = (
        binary_stream.iter_lines()
        if hasattr(binary_stream, "iter_lines")
        else binary_stream
    )
    return codecs.iterdecode(lines, "utf-8-sig", errors="replace")


def _to_number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise S3LookupError("S3 returned an invalid boolean transaction value.")


def _row_to_transaction(row: dict[str, str | None]) -> dict[str, Any]:
    normalized = {
        (name or "").strip().lower(): (value.strip() if value is not None else None)
        for name, value in row.items()
        if name is not None
    }
    try:
        return {
            "transaction_id": normalized.get("transaction_id"),
            "customer_id": normalized.get("customer_id"),
            "amount": _to_number(normalized.get("amount")),
            "currency": normalized.get("currency"),
            "amount_usd": _to_number(normalized.get("amount_usd")),
            "merchant_name": normalized.get("merchant_name"),
            "transaction_date": normalized.get("transaction_date"),
            "transaction_status": normalized.get("transaction_status"),
            "is_fraud": _to_bool(normalized.get("is_fraud")),
            "fraud_score": _to_number(normalized.get("fraud_score")),
        }
    except ValueError as exc:
        raise S3LookupError(
            "S3 returned a transaction with invalid numeric fields."
        ) from exc


def _search_object(
    client: Any, bucket: str, key: str, transaction_id: str
) -> dict[str, Any] | None:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    compressed = key.lower().endswith(".csv.gz")
    try:
        reader = csv.DictReader(_text_lines(body, compressed))
        if not reader.fieldnames or "transaction_id" not in {
            name.strip().lower() for name in reader.fieldnames
        }:
            raise S3LookupError(
                "A transaction CSV in S3 is missing the transaction_id column."
            )
        for row in reader:
            normalized_row = {
                (name or "").strip().lower(): value for name, value in row.items()
            }
            if (normalized_row.get("transaction_id") or "").strip() == transaction_id:
                return _row_to_transaction(normalized_row)
        return None
    finally:
        body.close()


def _csv_object_keys(paginator: Any, bucket: str, prefix: str) -> Iterable[str]:
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.lower().endswith((".csv", ".csv.gz")):
                yield key


def _lookup_sqlite(transaction_id: str) -> dict[str, Any] | None:
    try:
        database_uri = f"{SQLITE_DATABASE_PATH.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True)) as connection:
            row = connection.execute(
                """
                SELECT
                    transaction_id,
                    transaction_date,
                    customer_id,
                    amount,
                    currency,
                    amount_usd,
                    merchant_name,
                    transaction_status,
                    is_fraud,
                    fraud_score
                FROM transactions
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("Local SQLite transaction lookup failed (%s).", type(exc).__name__)
        raise S3LookupError(
            "Local SQLite transaction lookup failed. Check the database file and schema."
        ) from exc

    if row is None:
        return None
    return {
        "transaction_id": row[0],
        "customer_id": row[2],
        "amount": float(row[3]) if row[3] is not None else None,
        "currency": row[4],
        "amount_usd": float(row[5]) if row[5] is not None else None,
        "merchant_name": row[6],
        "transaction_date": row[1],
        "transaction_status": row[7],
        "is_fraud": bool(row[8]) if row[8] is not None else None,
        "fraud_score": float(row[9]) if row[9] is not None else None,
    }


def lookup_transaction(
    transaction_id: str, transaction_date: str | None = None
) -> dict[str, Any] | None:
    """Look up a transaction in local SQLite, falling back to S3 when absent.

    If the local database exists, it is authoritative for this lookup; S3 is only
    used when the local database file is missing.
    """
    if SQLITE_DATABASE_PATH.is_file():
        return _lookup_sqlite(transaction_id)

    bucket = os.getenv("S3_BUCKET", "").strip()
    if not bucket:
        raise S3ConfigurationError("S3_BUCKET must be configured for transaction lookup.")

    access_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
    if bool(access_key) != bool(secret_key):
        raise S3ConfigurationError(
            "Configure both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
            "or use an AWS role/default credential provider."
        )

    try:
        import boto3

        client_options: dict[str, Any] = {
            "region_name": os.getenv("AWS_DEFAULT_REGION", "us-east-1").strip(),
        }
        if access_key and secret_key:
            client_options.update(
                {
                    "aws_access_key_id": access_key,
                    "aws_secret_access_key": secret_key,
                    "aws_session_token": os.getenv("AWS_SESSION_TOKEN", "").strip() or None,
                }
            )
        elif os.getenv("AWS_SESSION_TOKEN", "").strip():
            raise S3ConfigurationError(
                "AWS_SESSION_TOKEN requires AWS_ACCESS_KEY_ID and "
                "AWS_SECRET_ACCESS_KEY."
            )
        client = boto3.client("s3", **client_options)
        prefix = _transactions_prefix()
        paginator = client.get_paginator("list_objects_v2")
        date_prefix = (
            _date_partition_prefix(prefix, transaction_date) if transaction_date else None
        )
        if date_prefix:
            for key in _csv_object_keys(paginator, bucket, date_prefix):
                result = _search_object(client, bucket, key, transaction_id)
                if result is not None:
                    return result

        keys = list(_csv_object_keys(paginator, bucket, prefix))
        if not keys:
            raise S3LookupError(
                f"No transaction CSV objects found under S3 prefix '{prefix}'."
            )

        remaining_keys = (
            [key for key in keys if not key.startswith(date_prefix)]
            if date_prefix
            else keys
        )
        for key in sorted(remaining_keys, reverse=True):
            result = _search_object(client, bucket, key, transaction_id)
            if result is not None:
                return result
        return None
    except (S3ConfigurationError, S3LookupError):
        raise
    except Exception as exc:
        logger.error("S3 transaction lookup failed (%s).", type(exc).__name__)
        raise S3LookupError(
            "S3 transaction lookup failed. Check read access to the bucket, "
            "transaction prefix, and CSV objects."
        ) from exc
