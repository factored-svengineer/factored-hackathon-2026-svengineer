"""Issue #13 — post-action verification and safe tool-failure fallbacks."""

from __future__ import annotations

import pytest

from app.graph import google_extractor
from app.graph.extract import extract_entities
from app.graph.nodes import Decision, act, verify
from app.graph.runner import run_dispute_graph
from app.graph.verify_ops import case_matches_expected, verify_case_persisted
from app.tools.resilience import ToolFailureKind, call_tool
from app.tools.store import (
    clear_dispute_cases,
    configure_store_failures,
    create_dispute_case,
    get_dispute_case,
)


@pytest.fixture(autouse=True)
def use_deterministic_extractor(monkeypatch):
    monkeypatch.setattr(
        google_extractor,
        "extract_entities_with_google",
        lambda text, language_hint=None: extract_entities(text),
    )
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda transaction_id, transaction_date=None: None,
    )


def setup_function() -> None:
    clear_dispute_cases()


def _clear_fraud_payload() -> dict:
    return {
        "text": "No reconozco un cargo de 45.51 USD en Empresa Telefonica TRX-VV2MMGPU6842YMOC1BHN",
        "language": "es",
        "is_fraud": True,
        "fraud_score": 97.45,
        "transaction_id": "TRX-VV2MMGPU6842YMOC1BHN",
        "amount": 45.51,
        "currency": "USD",
        "merchant_name": "Empresa Telefonica",
        "priority": "Medium",
    }


def test_call_tool_retries_transient_then_succeeds():
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("slow")
        return "ok"

    result = call_tool("flaky", flaky, retries=1)
    assert result.ok is True
    assert result.value == "ok"
    assert result.attempts == 2


def test_call_tool_exhausts_retries_without_claiming_success():
    def always_fail() -> None:
        raise ConnectionError("down")

    result = call_tool("always_fail", always_fail, retries=1)
    assert result.ok is False
    assert result.failure_kind == ToolFailureKind.TRANSIENT
    assert result.attempts == 2
    assert result.value is None


def test_verify_case_persisted_confirms_create():
    record = create_dispute_case(
        {
            "customer_id": "CLI-1",
            "status": "Resolved",
            "decision": "auto_resolve",
            "claimed_amount": 10.0,
        }
    )
    result = verify_case_persisted(record["complaint_id"])
    assert result.ok is True
    assert result.value["complaint_id"] == record["complaint_id"]
    ok, mismatches = case_matches_expected(
        result.value, {"decision": "auto_resolve", "customer_id": "CLI-1"}
    )
    assert ok is True
    assert mismatches == []


def test_verify_case_persisted_missing_id():
    result = verify_case_persisted(None)
    assert result.ok is False
    assert result.failure_kind == ToolFailureKind.NOT_FOUND


def test_create_failure_falls_back_to_escalate_never_claims_success():
    # retries=1 → two attempts; force both to fail
    configure_store_failures(create_failures=2)
    result = run_dispute_graph(_clear_fraud_payload())

    assert result["decision"] == Decision.ESCALATE.value
    assert result["verified"] is False
    assert result["complaint_id"] is None
    assert result["fallback_applied"] == "create_case_failed_escalate"
    assert result["tool_failures"]
    assert "escalate" in result["nodes_visited"]
    assert result["handoff"]["reason"].startswith("tool_failure:create_dispute_case")
    assert any(
        a.get("action_type") == "create_dispute_case" and a.get("status") == "failed"
        for a in result["actions_taken"]
    )


def test_create_retries_then_succeeds():
    configure_store_failures(create_failures=1)
    result = run_dispute_graph(_clear_fraud_payload())

    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["verified"] is True
    assert result["complaint_id"]
    assert get_dispute_case(result["complaint_id"]) is not None
    assert result.get("fallback_applied") is None


def test_verify_failure_demotes_auto_resolve_to_escalate():
    configure_store_failures(get_failures=2)  # verify retries once → two attempts
    result = run_dispute_graph(_clear_fraud_payload())

    assert result["decision"] == Decision.ESCALATE.value
    assert result["verified"] is False
    assert result["fallback_applied"] == "verify_failed_demote_auto_resolve_to_escalate"
    assert "escalate" in result["nodes_visited"]
    assert result["complaint_id"]  # create succeeded; verify re-read failed
    assert result["handoff"] is not None


def test_verify_clarify_without_prompts_is_unverified():
    state = act(
        {
            "decision": Decision.CLARIFY,
            "open_questions_fields": [],
            "language": "es",
            "text": "hola",
        }
    )
    # Force empty clarification artifacts
    state["clarification_prompts"] = []
    state["open_questions"] = []
    out = verify(state)
    assert out["verified"] is False
    assert out["fallback_applied"] == "verify_failed_mark_unverified"
