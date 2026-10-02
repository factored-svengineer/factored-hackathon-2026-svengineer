"""In-memory dispute case store plus read-only S3 transaction lookup."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

_LOCK = Lock()
_CASES: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_dispute_case(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a dispute case and return the stored record."""
    case_id = payload.get("complaint_id") or f"CMP-{uuid4().hex[:20].upper()}"
    record = {
        **payload,
        "complaint_id": case_id,
        "status": payload.get("status") or "Open",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    with _LOCK:
        _CASES[case_id] = deepcopy(record)
    return deepcopy(record)


def get_dispute_case(complaint_id: str) -> dict[str, Any] | None:
    with _LOCK:
        record = _CASES.get(complaint_id)
        return deepcopy(record) if record else None


def list_dispute_cases() -> list[dict[str, Any]]:
    with _LOCK:
        return [deepcopy(v) for v in _CASES.values()]


def clear_dispute_cases() -> None:
    """Test helper."""
    with _LOCK:
        _CASES.clear()


def get_transaction(
    transaction_id: str, transaction_date: str | None = None
) -> dict[str, Any] | None:
    """Stream the matching CSV row from the source S3 bucket."""
    from app.tools.aws_data import lookup_transaction

    return lookup_transaction(transaction_id, transaction_date)
