from __future__ import annotations

from pathlib import Path

import pytest

from ingestion import s3_ingest


class FakePaginator:
    def __init__(self, keys: list[str]):
        self.keys = keys

    def paginate(self, **kwargs):
        yield {"Contents": [{"Key": key} for key in self.keys]}


class FakeS3Client:
    def __init__(self, keys: list[str]):
        self.keys = keys
        self.downloaded: list[tuple[str, str]] = []

    def get_paginator(self, operation: str):
        assert operation == "list_objects_v2"
        return FakePaginator(self.keys)

    def download_file(self, bucket: str, key: str, filename: str):
        self.downloaded.append((bucket, key))
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).touch()


def test_ingest_priority_tables_downloads_files_and_shards(monkeypatch, tmp_path):
    tables = s3_ingest.PRIORITY_TABLES
    keys = [
        f"raw/{tables[0]}.csv",
        f"raw/{tables[1]}/part-000.parquet",
        f"raw/{tables[2]}/part-000.jsonl",
        f"raw/{tables[3]}/part-000.csv.gz",
        "raw/complaints_archive.csv",
        "raw/transactions/_SUCCESS",
    ]
    client = FakeS3Client(keys)
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_PREFIX", "raw/")
    monkeypatch.setattr(s3_ingest, "_s3_client", lambda: client)

    paths = s3_ingest.ingest_priority_tables(tmp_path)

    assert set(paths) == set(tables)
    assert all(path.is_dir() for path in paths.values())
    assert len(client.downloaded) == 4
    assert (tmp_path / "complaints" / "complaints.csv").is_file()
    assert (tmp_path / "transactions" / "part-000.parquet").is_file()


def test_ingest_table_reports_missing_dataset(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.delenv("S3_PREFIX", raising=False)
    monkeypatch.setattr(s3_ingest, "_s3_client", lambda: FakeS3Client([]))

    with pytest.raises(FileNotFoundError, match="complaints"):
        s3_ingest.ingest_table("complaints", tmp_path)


def test_s3_client_requires_environment_credentials(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(EnvironmentError, match="AWS_ACCESS_KEY_ID"):
        s3_ingest._s3_client()