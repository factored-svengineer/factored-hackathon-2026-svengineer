"""Read-only S3 transaction lookup tests using a mocked boto3 client."""

from __future__ import annotations

import io
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

    def paginate(self, **kwargs):
        assert kwargs == {
            "Bucket": "test-public-dataset",
            "Prefix": "data/transactions/",
        }
        yield {"Contents": [{"Key": key} for key in sorted(self.keys)]}


class FakeS3Client:
    def __init__(self, objects):
        self.objects = objects
        self.read_keys = []

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        return FakePaginator(list(self.objects))

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
    date_key = (
        "data/transactions/year=2026/month=10/day=02/transactions_20261002.csv"
    )
    late_key = (
        "data/transactions/year=2026/month=10/day=03/transactions_20261003.csv"
    )
    old_key = (
        "data/transactions/year=2026/month=10/day=01/transactions_20261001.csv"
    )
    objects = {
        date_key: CSV_HEADER + make_csv_row("another-id", "2026-10-02", "2026-10-02"),
        late_key: CSV_HEADER + make_csv_row("txn-1", "2026-10-03", "2026-10-02"),
        old_key: CSV_HEADER + make_csv_row("old-id", "2026-10-01", "2026-10-01"),
    }
    s3_client = FakeS3Client(objects)
    install_fake_boto3(monkeypatch, s3_client)

    result = aws_data.lookup_transaction("txn-1", "2026-10-02")

    assert result == {
        "transaction_id": "txn-1",
        "customer_id": "CUST-1",
        "amount": 42.0,
        "currency": "USD",
        "amount_usd": 42.0,
        "merchant_name": "Google Play",
        "transaction_date": "2026-10-02 12:00:00",
        "transaction_status": "Approved",
        "is_fraud": True,
        "fraud_score": 98.0,
    }
    assert s3_client.read_keys == [date_key, old_key, late_key]


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
