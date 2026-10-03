"""Read-only S3 transaction lookup tests using a mocked boto3 client."""

from __future__ import annotations

import io
import sqlite3
import sys
from types import ModuleType

import pytest
from app.tools import aws_data

CSV_HEADER = (
    "transaction_id,transaction_date,process_date,product_id,customer_id,"
    "transaction_type,transaction_category,amount,currency,amount_usd,channel,"
    "branch_id,merchant_name,merchant_category,transaction_country,"
    "transaction_city,transaction_status,response_code,is_fraud,fraud_score,"
    "latitude,longitude\n"
)


@pytest.fixture(autouse=True)
def isolate_sqlite_database(monkeypatch, tmp_path):
    monkeypatch.setattr(
        aws_data, "SQLITE_DATABASE_PATH", tmp_path / "transactions.sqlite3"
    )


def set_s3_environment(monkeypatch):
    values = {
        "AWS_ACCESS_KEY_ID": "test-access-key",
        "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        "AWS_DEFAULT_REGION": "us-east-1",
        "S3_BUCKET": "test-public-dataset",
        "S3_TRANSACTIONS_PREFIX": "data/transactions/",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def make_csv_row(transaction_id, process_date, transaction_date):
    return (
        f"{transaction_id},{transaction_date} 12:00:00,{process_date},"
        "PROD-1,CUST-1,Purchase,Entertainment,42.00,USD,42.00,POS,,"
        "Google Play,Digital,Argentina,Buenos Aires,Approved,,true,98.00,,\n"
    )


class FakePaginator:
    def __init__(self, keys):
        self.keys = keys
        self.prefixes = []

    def paginate(self, **kwargs):
        assert kwargs["Bucket"] == "test-public-dataset"
        prefix = kwargs["Prefix"]
        self.prefixes.append(prefix)
        yield {
            "Contents": [
                {"Key": key} for key in sorted(self.keys) if key.startswith(prefix)
            ]
        }


class FakeS3Client:
    def __init__(self, objects):
        self.objects = objects
        self.read_keys = []
        self.paginator = FakePaginator(list(objects))

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        return self.paginator

    def get_object(self, *, Bucket, Key):
        assert Bucket == "test-public-dataset"
        self.read_keys.append(Key)
        return {"Body": io.BytesIO(self.objects[Key].encode("utf-8"))}


def install_fake_boto3(monkeypatch, s3_client):
    boto3_module = ModuleType("boto3")

    def fake_client(service, **kwargs):
        assert service == "s3"
        assert kwargs["region_name"] == "us-east-1"
        assert kwargs["aws_access_key_id"] == "test-access-key"
        assert kwargs["aws_secret_access_key"] == "test-secret-key"
        return s3_client

    boto3_module.client = fake_client
    monkeypatch.setitem(sys.modules, "boto3", boto3_module)


def test_lookup_streams_date_partition_then_falls_back_for_late_arrival(
    monkeypatch,
):
    set_s3_environment(monkeypatch)
    date_key = "data/transactions/year=2026/month=06/day=17/transactions_20260617.csv"
    late_key = "data/transactions/year=2026/month=06/day=16/transactions_20260616.csv"
    old_key = "data/transactions/year=2026/month=06/day=15/transactions_20260615.csv"
    objects = {
        date_key: CSV_HEADER + make_csv_row("another-id", "2026-06-17", "2026-06-17"),
        late_key: CSV_HEADER + make_csv_row("txn-1", "2026-06-16", "2026-06-17"),
        old_key: CSV_HEADER + make_csv_row("old-id", "2026-06-15", "2026-06-15"),
    }
    s3_client = FakeS3Client(objects)
    install_fake_boto3(monkeypatch, s3_client)

    result = aws_data.lookup_transaction("txn-1", "2026-06-17")

    assert result == {
        "transaction_id": "txn-1",
        "customer_id": "CUST-1",
        "amount": 42.0,
        "currency": "USD",
        "amount_usd": 42.0,
        "merchant_name": "Google Play",
        "transaction_date": "2026-06-17 12:00:00",
        "transaction_status": "Approved",
        "is_fraud": True,
        "fraud_score": 98.0,
    }
    assert s3_client.read_keys == [date_key, late_key]
    assert s3_client.paginator.prefixes == [
        "data/transactions/year=2026/month=06/day=17/",
        "data/transactions/",
    ]


def test_lookup_does_not_list_all_partitions_when_date_partition_matches(monkeypatch):
    set_s3_environment(monkeypatch)
    key = "data/transactions/year=2026/month=06/day=17/transactions_20260617.csv"
    s3_client = FakeS3Client(
        {key: CSV_HEADER + make_csv_row("txn-1", "2026-06-17", "2026-06-17")}
    )
    install_fake_boto3(monkeypatch, s3_client)

    result = aws_data.lookup_transaction("txn-1", "2026-06-17")

    assert result["transaction_id"] == "txn-1"
    assert s3_client.read_keys == [key]
    assert s3_client.paginator.prefixes == [
        "data/transactions/year=2026/month=06/day=17/"
    ]


def test_lookup_without_date_scans_csv_and_ignores_non_csv(monkeypatch):
    set_s3_environment(monkeypatch)
    csv_key = "data/transactions/year=2023/month=06/day=17/transactions_20230617.csv"
    objects = {
        csv_key: CSV_HEADER + make_csv_row("txn-1", "2023-06-17", "2023-06-17"),
        "data/transactions/README.txt": "not a transaction file",
    }
    s3_client = FakeS3Client(objects)
    install_fake_boto3(monkeypatch, s3_client)

    result = aws_data.lookup_transaction("txn-1")

    assert result["transaction_id"] == "txn-1"
    assert s3_client.read_keys == [csv_key]


def test_lookup_returns_none_if_id_not_found(monkeypatch):
    set_s3_environment(monkeypatch)
    key = "data/transactions/year=2023/month=06/day=17/transactions_20230617.csv"
    s3_client = FakeS3Client(
        {key: CSV_HEADER + make_csv_row("other-id", "2023-06-17", "2023-06-17")}
    )
    install_fake_boto3(monkeypatch, s3_client)

    assert aws_data.lookup_transaction("missing-id", "2023-06-17") is None
    assert s3_client.read_keys == [key]


def test_lookup_requires_bucket(monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)

    with pytest.raises(aws_data.S3ConfigurationError, match="S3_BUCKET"):
        aws_data.lookup_transaction("txn-1")


def test_lookup_requires_complete_static_credentials(monkeypatch):
    set_s3_environment(monkeypatch)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(aws_data.S3ConfigurationError, match="both"):
        aws_data.lookup_transaction("txn-1")


def test_lookup_reports_missing_transaction_objects(monkeypatch):
    set_s3_environment(monkeypatch)
    s3_client = FakeS3Client({})
    install_fake_boto3(monkeypatch, s3_client)

    with pytest.raises(aws_data.S3LookupError, match="No transaction CSV"):
        aws_data.lookup_transaction("txn-1")


def test_lookup_rejects_csv_without_transaction_id_column(monkeypatch):
    set_s3_environment(monkeypatch)
    key = "data/transactions/year=2023/month=06/day=17/transactions_20230617.csv"
    s3_client = FakeS3Client({key: "customer_id,amount\nCUST-1,42.00\n"})
    install_fake_boto3(monkeypatch, s3_client)

    with pytest.raises(aws_data.S3LookupError, match="transaction_id column"):
        aws_data.lookup_transaction("txn-1")


def test_lookup_reads_existing_sqlite_without_creating_s3_client(monkeypatch):
    connection = sqlite3.connect(aws_data.SQLITE_DATABASE_PATH)
    connection.execute(
        """
        CREATE TABLE transactions (
            transaction_id TEXT PRIMARY KEY,
            transaction_date TEXT,
            process_date TEXT,
            customer_id TEXT,
            amount REAL,
            currency TEXT,
            amount_usd REAL,
            merchant_name TEXT,
            transaction_status TEXT,
            is_fraud INTEGER,
            fraud_score REAL
        )
        """
    )
    connection.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "txn-sqlite",
            "2026-06-12 01:27:38",
            "2026-06-11",
            "customer-1",
            42.5,
            "USD",
            42.5,
            "Merchant",
            "Approved",
            1,
            95.1,
        ),
    )
    connection.commit()
    connection.close()

    def fail_if_s3_is_used(*args, **kwargs):
        pytest.fail("S3 should not be used when the local database exists.")

    monkeypatch.setattr(aws_data, "_csv_object_keys", fail_if_s3_is_used)
    monkeypatch.setitem(sys.modules, "boto3", ModuleType("boto3"))

    result = aws_data.lookup_transaction("txn-sqlite", "ignored-date")

    assert result == {
        "transaction_id": "txn-sqlite",
        "customer_id": "customer-1",
        "amount": 42.5,
        "currency": "USD",
        "amount_usd": 42.5,
        "merchant_name": "Merchant",
        "transaction_date": "2026-06-12 01:27:38",
        "transaction_status": "Approved",
        "is_fraud": True,
        "fraud_score": 95.1,
    }


def test_lookup_does_not_fall_back_to_s3_if_existing_sqlite_lacks_table(
    monkeypatch,
):
    aws_data.SQLITE_DATABASE_PATH.touch()

    def fail_if_s3_is_used(*args, **kwargs):
        pytest.fail("A broken local database must not silently fall back to S3.")

    monkeypatch.setattr(aws_data, "_csv_object_keys", fail_if_s3_is_used)

    with pytest.raises(aws_data.S3LookupError, match="Local SQLite"):
        aws_data.lookup_transaction("txn-1")
