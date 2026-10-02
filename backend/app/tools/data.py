"""Tool functions for AWS transaction lookups and local dispute-case storage."""

from __future__ import annotations

from typing import Any

from app.tools.store import create_dispute_case as _create_case
from app.tools.store import get_dispute_case
from app.tools.store import get_transaction as _get_txn


def get_transaction(
    transaction_id: str, transaction_date: str | None = None
) -> dict[str, Any] | None:
    """Look up a transaction including is_fraud / fraud_score."""
    return _get_txn(transaction_id, transaction_date)


def get_complaint(complaint_id: str) -> dict[str, Any] | None:
    """Look up a complaint / dispute case from the local store."""
    return get_dispute_case(complaint_id)


def get_customer(customer_id: str) -> dict[str, Any] | None:
    """Look up customer profile — not wired yet."""
    return None


def get_call_center_interactions(customer_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch recent call-center interactions — not wired yet."""
    return []


def create_dispute_case(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a dispute case and return the persisted record (for verify node)."""
    return _create_case(payload)
