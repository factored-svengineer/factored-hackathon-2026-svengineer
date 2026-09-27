"""Tool functions that query dispute-related data (DuckDB / S3-backed)."""

from __future__ import annotations

from typing import Any


def get_transaction(transaction_id: str) -> dict[str, Any] | None:
    """Look up a transaction including is_fraud / fraud_score."""
    raise NotImplementedError("Query transactions via DuckDB over S3")


def get_complaint(complaint_id: str) -> dict[str, Any] | None:
    """Look up a complaint record (description used for classification)."""
    raise NotImplementedError("Query complaints via DuckDB over S3")


def get_customer(customer_id: str) -> dict[str, Any] | None:
    """Look up customer profile."""
    raise NotImplementedError("Query customers via DuckDB over S3")


def get_call_center_interactions(customer_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch recent call-center interactions / transcripts for a customer."""
    raise NotImplementedError("Query call_center_interactions via DuckDB over S3")


def create_dispute_case(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a dispute case and return the persisted record (for verify node)."""
    raise NotImplementedError("Persist dispute case and return confirmation id")
