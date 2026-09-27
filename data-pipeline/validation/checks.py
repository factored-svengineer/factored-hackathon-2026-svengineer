"""Lightweight quality checks for ingested dispute tables.

Detect nulls, duplicates, and out-of-contract values.
Swap/extend with pandera or Great Expectations as needed.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


REQUIRED_COLUMNS: dict[str, list[str]] = {
    "complaints": ["complaint_id", "description"],
    "transactions": ["transaction_id", "amount", "is_fraud", "fraud_score"],
    "customers": ["customer_id"],
    "call_center_interactions": ["interaction_id", "customer_id"],
}


def validate_table(name: str, df: pd.DataFrame) -> dict[str, Any]:
    required = REQUIRED_COLUMNS.get(name, [])
    missing_cols = [c for c in required if c not in df.columns]
    null_counts = {c: int(df[c].isna().sum()) for c in required if c in df.columns}
    duplicate_rows = int(df.duplicated().sum())

    return {
        "table": name,
        "rows": len(df),
        "missing_columns": missing_cols,
        "null_counts": null_counts,
        "duplicate_rows": duplicate_rows,
        "ok": not missing_cols and duplicate_rows == 0,
    }
