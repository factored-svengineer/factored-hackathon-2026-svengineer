"""Optional local DuckDB reads over data/raw (gitignored sample downloads)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def _raw_root() -> Path:
    env = os.getenv("DATA_RAW_DIR")
    if env:
        return Path(env)
    # backend/app/tools -> repo root
    return Path(__file__).resolve().parents[3] / "data" / "raw"


@lru_cache(maxsize=1)
def _transaction_index() -> dict[str, dict[str, Any]]:
    root = _raw_root() / "transactions"
    if not root.exists():
        return {}
    try:
        import duckdb
    except ImportError:
        return {}

    files = sorted(root.rglob("*.csv"))
    if not files:
        return {}
    # Limit scan for local skeleton performance
    sample = files[:20]
    con = duckdb.connect(database=":memory:")
    index: dict[str, dict[str, Any]] = {}
    for path in sample:
        try:
            rel = con.execute(
                """
                SELECT transaction_id, customer_id, amount, currency, amount_usd,
                       merchant_name, transaction_date, transaction_status,
                       is_fraud, fraud_score
                FROM read_csv_auto(?, HEADER=TRUE)
                """,
                [str(path)],
            )
            for row in rel.fetchall():
                cols = [
                    "transaction_id",
                    "customer_id",
                    "amount",
                    "currency",
                    "amount_usd",
                    "merchant_name",
                    "transaction_date",
                    "transaction_status",
                    "is_fraud",
                    "fraud_score",
                ]
                item = dict(zip(cols, row, strict=True))
                tid = str(item["transaction_id"])
                index[tid] = item
        except (OSError, ValueError, duckdb.Error):
            continue
    return index


def lookup_transaction(transaction_id: str) -> dict[str, Any] | None:
    return _transaction_index().get(transaction_id)
