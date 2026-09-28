"""Schema and quality checks for ingested dispute tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pandera.pandas as pa

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "complaints": ["complaint_id", "description"],
    "transactions": ["transaction_id", "amount", "is_fraud", "fraud_score"],
    "customers": ["customer_id"],
    "call_center_interactions": ["interaction_id", "customer_id"],
}

TABLE_SCHEMAS: dict[str, pa.DataFrameSchema] = {
    "complaints": pa.DataFrameSchema(
        {
            "complaint_id": pa.Column(str, nullable=False, unique=True, coerce=True),
            "description": pa.Column(str, nullable=False, coerce=True),
        },
        strict=False,
    ),
    "transactions": pa.DataFrameSchema(
        {
            "transaction_id": pa.Column(str, nullable=False, unique=True, coerce=True),
            "amount": pa.Column(float, nullable=False, checks=pa.Check.ge(0), coerce=True),
            "is_fraud": pa.Column(
                checks=pa.Check.isin([True, False, 0, 1]), nullable=False
            ),
            "fraud_score": pa.Column(
                float,
                nullable=False,
                checks=pa.Check.in_range(0, 1),
                coerce=True,
            ),
        },
        strict=False,
    ),
    "customers": pa.DataFrameSchema(
        {
            "customer_id": pa.Column(str, nullable=False, unique=True, coerce=True),
        },
        strict=False,
    ),
    "call_center_interactions": pa.DataFrameSchema(
        {
            "interaction_id": pa.Column(str, nullable=False, unique=True, coerce=True),
            "customer_id": pa.Column(str, nullable=False, coerce=True),
        },
        strict=False,
    ),
}


def validate_table(name: str, df: pd.DataFrame) -> dict[str, Any]:
    required = REQUIRED_COLUMNS.get(name, [])
    missing_cols = [c for c in required if c not in df.columns]
    null_counts = {c: int(df[c].isna().sum()) for c in required if c in df.columns}
    duplicate_rows = int(df.duplicated().sum())
    schema_errors: list[dict[str, Any]] = []

    if name not in TABLE_SCHEMAS:
        schema_errors.append({"error": f"No schema is registered for table '{name}'"})
    else:
        try:
            TABLE_SCHEMAS[name].validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            schema_errors = exc.failure_cases.astype(str).to_dict("records")
        except pa.errors.SchemaError as exc:
            schema_errors = [{"error": str(exc)}]

    return {
        "table": name,
        "rows": len(df),
        "missing_columns": missing_cols,
        "null_counts": null_counts,
        "duplicate_rows": duplicate_rows,
        "schema_errors": schema_errors,
        "ok": not missing_cols and duplicate_rows == 0 and not schema_errors,
    }


def _read_table_file(path: Path) -> pd.DataFrame:
    filename = path.name.lower()
    if filename.endswith((".csv", ".csv.gz")):
        return pd.read_csv(path)
    if filename.endswith((".parquet", ".parquet.gz")):
        return duckdb.read_parquet(str(path)).df()
    if filename.endswith((".jsonl", ".ndjson")):
        return pd.read_json(path, lines=True)
    if filename.endswith(".json"):
        return pd.read_json(path)
    raise ValueError(f"Unsupported table file: {path}")


def validate_ingested_tables(data_dir: str | Path = "data/raw") -> dict[str, dict[str, Any]]:
    """Validate each priority table, combining its files so shard duplicates are caught."""
    root = Path(data_dir)
    reports: dict[str, dict[str, Any]] = {}
    supported_suffixes = (".csv", ".csv.gz", ".parquet", ".parquet.gz", ".json", ".jsonl", ".ndjson")

    for name, required in REQUIRED_COLUMNS.items():
        table_dir = root / name
        files = (
            sorted(
                path
                for path in table_dir.rglob("*")
                if path.is_file() and path.name.lower().endswith(supported_suffixes)
            )
            if table_dir.is_dir()
            else []
        )
        frames: list[pd.DataFrame] = []
        read_errors: list[str] = []

        for path in files:
            try:
                frames.append(_read_table_file(path))
            except (OSError, ValueError, duckdb.Error) as exc:
                read_errors.append(f"{path}: {exc}")

        combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
        report = validate_table(name, combined)
        if not files:
            report["schema_errors"].append(
                {"error": f"No supported data files found in {table_dir}"}
            )
        report["sources"] = [str(path) for path in files]
        report["read_errors"] = read_errors
        report["ok"] = report["ok"] and bool(files) and not read_errors
        if not files:
            report["missing_columns"] = required
        reports[name] = report

    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ingested priority tables.")
    parser.add_argument("--data-dir", default="data/raw", help="Root directory containing table folders")
    args = parser.parse_args()
    reports = validate_ingested_tables(args.data_dir)
    print(json.dumps(reports, indent=2))
    return int(any(not report["ok"] for report in reports.values()))


if __name__ == "__main__":
    raise SystemExit(main())
