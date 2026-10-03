"""In-memory dispute case store plus read-only S3 transaction lookup."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

_LOCK = Lock()
_CASES: dict[str, dict[str, Any]] = {}
# Test hooks — never enable in production paths except via tests.
_FORCE_CREATE_FAILURES_REMAINING = 0
_FORCE_GET_FAILURES_REMAINING = 0
_FORCE_CREATE_EXCEPTION: type[Exception] = ConnectionError
_FORCE_GET_EXCEPTION: type[Exception] = ConnectionError


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def configure_store_failures(
    *,
    create_failures: int = 0,
    get_failures: int = 0,
    create_exc: type[Exception] = ConnectionError,
    get_exc: type[Exception] = ConnectionError,
) -> None:
    """Test-only: make the next N create/get calls fail."""
    global _FORCE_CREATE_FAILURES_REMAINING, _FORCE_GET_FAILURES_REMAINING
    global _FORCE_CREATE_EXCEPTION, _FORCE_GET_EXCEPTION
    _FORCE_CREATE_FAILURES_REMAINING = create_failures
    _FORCE_GET_FAILURES_REMAINING = get_failures
    _FORCE_CREATE_EXCEPTION = create_exc
    _FORCE_GET_EXCEPTION = get_exc


def create_dispute_case(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a dispute case and return the stored record."""
    global _FORCE_CREATE_FAILURES_REMAINING
    if _FORCE_CREATE_FAILURES_REMAINING > 0:
        _FORCE_CREATE_FAILURES_REMAINING -= 1
        raise _FORCE_CREATE_EXCEPTION("forced create_dispute_case failure")

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
    global _FORCE_GET_FAILURES_REMAINING
    if _FORCE_GET_FAILURES_REMAINING > 0:
        _FORCE_GET_FAILURES_REMAINING -= 1
        raise _FORCE_GET_EXCEPTION("forced get_dispute_case failure")

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
    configure_store_failures(create_failures=0, get_failures=0)


def get_transaction(
    transaction_id: str, transaction_date: str | None = None
) -> dict[str, Any] | None:
    """Stream the matching CSV row from the source S3 bucket."""
    from app.tools.aws_data import lookup_transaction

    return lookup_transaction(transaction_id, transaction_date)
