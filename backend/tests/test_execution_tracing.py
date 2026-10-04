"""Issue #14 — auditable execution tracing (rules + records, not CoT)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.graph import google_extractor
from app.graph.extract import extract_entities
from app.graph.nodes import Decision
from app.graph.runner import run_dispute_graph
from app.graph.tracing import (
    EXPLAINABILITY_CONTRACT,
    ROLE_BUSINESS_RULES,
    ROLE_LLM_EXTRACTION,
    assert_trace_has_no_forbidden_fields,
)
from app.main import app
from app.tools.store import clear_dispute_cases

client = TestClient(app)


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


def _clear_fraud_payload(**extra):
    payload = {
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
    payload.update(extra)
    return payload


def test_trace_contract_endpoint():
    response = client.get("/graph/trace-contract")
    assert response.status_code == 200
    body = response.json()
    assert body["explainability"]["llm_role"].startswith("Gemini extracts")
    assert "chain_of_thought" in body["forbidden_fields"]
    assert "business_rules" in body["step_roles"]


def test_execution_trace_marks_decide_as_business_rules_only():
    result = run_dispute_graph(_clear_fraud_payload())
    trace = result["execution_trace"]

    assert result["trace_id"] == trace["trace_id"]
    assert trace["explainability"] == EXPLAINABILITY_CONTRACT
    assert assert_trace_has_no_forbidden_fields(trace) == []

    decide_steps = [s for s in trace["steps"] if s["node"] == "decide"]
    assert len(decide_steps) == 1
    decide = decide_steps[0]
    assert decide["roles"] == [ROLE_BUSINESS_RULES]
    assert ROLE_LLM_EXTRACTION not in decide["roles"]
    assert decide["outputs"]["decision"] in {
        Decision.AUTO_RESOLVE.value,
        Decision.CLARIFY.value,
        Decision.ESCALATE.value,
    }
    assert decide["reasons"]
    assert "No LLM participates" in decide["summary"]


def test_understand_can_use_llm_extraction_but_not_as_decision():
    result = run_dispute_graph(
        {"text": "No reconozco un cargo de $10", "language": "es"}
    )
    trace = result["execution_trace"]
    understand = next(s for s in trace["steps"] if s["node"] == "understand")
    # Extraction may run; decision authority remains rules.
    decide = next(s for s in trace["steps"] if s["node"] == "decide")
    assert decide["roles"] == [ROLE_BUSINESS_RULES]
    assert trace["decision"] == result["decision"]
    assert "llm_role" in trace["explainability"]
    assert understand["inputs"]["gemini_invoked"] in (True, False)


def test_trace_emits_structured_log_lines(caplog):
    with caplog.at_level(logging.INFO, logger="app.graph.trace"):
        result = run_dispute_graph(
            {"text": "I dispute an unknown charge", "language": "en"}
        )
    assert result["execution_trace"]["trace_id"]
    assert assert_trace_has_no_forbidden_fields(result["execution_trace"]) == []
    messages = [r.getMessage() for r in caplog.records if r.name == "app.graph.trace"]
    assert any('"event": "dispute_execution_trace"' in m for m in messages)
    assert any('"event": "dispute_execution_step"' in m for m in messages)
    # Contract may name forbidden fields; ensure no CoT payload key is logged.
    assert all('"chain_of_thought":' not in m for m in messages)


def test_api_triage_returns_execution_trace():
    response = client.post(
        "/disputes/triage",
        json={
            "text": "I dispute an unknown charge",
            "language": "en",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"]
    assert body["execution_trace"]["trace_id"] == body["trace_id"]
    assert body["execution_trace"]["explainability"]["decision_role"].startswith(
        "Business policy"
    )
    decide = next(s for s in body["execution_trace"]["steps"] if s["node"] == "decide")
    assert decide["roles"] == [ROLE_BUSINESS_RULES]


def test_approval_gate_is_traced_without_act():
    result = run_dispute_graph(
        _clear_fraud_payload(require_approval=True)
    )
    assert result["approval_required"] is True
    assert result["nodes_visited"] == ["understand", "decide"]
    nodes = [s["node"] for s in result["execution_trace"]["steps"]]
    assert "approval_gate" in nodes
    assert "act" not in nodes
    gate = next(s for s in result["execution_trace"]["steps"] if s["node"] == "approval_gate")
    assert ROLE_BUSINESS_RULES in gate["roles"]
    assert any("human_approval_required" in r for r in gate["reasons"])
