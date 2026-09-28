from __future__ import annotations

import duckdb
import pandas as pd
from validation.checks import validate_table


def test_valid_transaction_table_passes_and_allows_extra_columns():
    frame = pd.DataFrame(
        {
            "transaction_id": ["txn-1", "txn-2"],
            "amount": [10.0, 20.0],
            "is_fraud": [False, True],
            "fraud_score": [0.1, 0.9],
            "source_note": ["first", "second"],
        }
    )

    report = validate_table("transactions", frame)

    assert report["ok"] is True
    assert report["schema_errors"] == []


def test_nulls_fail_validation():
    frame = pd.DataFrame({"complaint_id": ["cmp-1"], "description": [None]})

    report = validate_table("complaints", frame)

    assert report["ok"] is False
    assert report["null_counts"]["description"] == 1
    assert report["schema_errors"]


def test_duplicate_identifier_fails_validation():
    frame = pd.DataFrame(
        {"customer_id": ["cust-1", "cust-1"], "segment": ["a", "b"]}
    )

    report = validate_table("customers", frame)

    assert report["ok"] is False
    assert report["duplicate_rows"] == 0
    assert report["schema_errors"]


def test_out_of_contract_values_fail_validation():
    frame = pd.DataFrame(
        {
            "transaction_id": ["txn-1"],
            "amount": [-1],
            "is_fraud": [False],
            "fraud_score": [1.2],
        }
    )

    report = validate_table("transactions", frame)

    assert report["ok"] is False
    assert report["schema_errors"]


def test_missing_columns_and_unknown_tables_fail_validation():
    missing = validate_table("complaints", pd.DataFrame({"complaint_id": ["cmp-1"]}))
    unknown = validate_table("other", pd.DataFrame())

    assert missing["ok"] is False
    assert missing["missing_columns"] == ["description"]
    assert unknown["ok"] is False
    assert unknown["schema_errors"]


def test_ingested_shards_are_combined_before_validation(tmp_path):
    table_dir = tmp_path / "customers"
    table_dir.mkdir()
    pd.DataFrame({"customer_id": ["cust-1"]}).to_csv(table_dir / "part-1.csv", index=False)
    pd.DataFrame({"customer_id": ["cust-1"]}).to_csv(table_dir / "part-2.csv", index=False)

    from validation.checks import validate_ingested_tables

    report = validate_ingested_tables(tmp_path)["customers"]

    assert report["ok"] is False
    assert len(report["sources"]) == 2
    assert report["schema_errors"]


def test_ingested_parquet_is_validated(tmp_path):
    table_dir = tmp_path / "customers"
    table_dir.mkdir()
    parquet_path = table_dir / "part-1.parquet"
    duckdb.from_df(pd.DataFrame({"customer_id": ["cust-1"]})).write_parquet(
        str(parquet_path)
    )

    from validation.checks import validate_ingested_tables

    report = validate_ingested_tables(tmp_path)["customers"]

    assert report["ok"] is True
    assert report["sources"] == [str(parquet_path)]