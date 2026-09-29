"""Tests for explicit ambiguity / abstention (Issue #9)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.graph.ambiguity import (
    FORBIDDEN_INVENTIONS,
    AmbiguityKind,
    AbstentionMode,
    assess_ambiguity,
)
from app.graph.nodes import Decision
from app.graph.runner import run_dispute_graph
from app.main import app
from app.tools.store import clear_dispute_cases

client = TestClient(app)


def setup_function() -> None:
    clear_dispute_cases()


def test_assess_missing_amount_date_merchant():
    result = assess_ambiguity(
        amount=None,
        transaction_id=None,
        merchant_name=None,
        transaction_date=None,
        text="Creo que me cobraron algo raro",
    )
    assert result.is_ambiguous is True
    assert result.abstention_mode == AbstentionMode.CLARIFY
    assert AmbiguityKind.MISSING_AMOUNT in result.kinds
    assert AmbiguityKind.MISSING_TRANSACTION_REF in result.kinds
    assert AmbiguityKind.UNCLEAR_INTENT in result.kinds
    assert "amount" in result.forbidden_inventions


def test_ambiguous_fraud_score_abstains_from_auto_resolve():
    result = assess_ambiguity(
        amount=200.0,
        transaction_id="TRX-1",
        merchant_name="Shop",
        transaction_date="2024-01-01",
        is_fraud=False,
        fraud_score_normalized=0.55,
        ambiguous_fraud=True,
    )
    assert result.is_ambiguous is True
    assert AmbiguityKind.AMBIGUOUS_FRAUD_SCORE in result.kinds
    assert result.abstention_mode == AbstentionMode.ABSTAIN


def test_graph_never_auto_resolves_when_amount_missing():
    """Archetype CMP-UIWYTUU… — no monto → clarify + abstention."""
    result = run_dispute_graph(
        {
            "text": "Creo que me cobraron algo que no reconozco, pero no tengo el monto ni la fecha",
            "language": "es",
            "priority": "Low",
            "status": "Open",
            # Explicitly no amount / txn — do not invent
            "amount": None,
            "transaction_id": None,
        }
    )
    assert result["decision"] == Decision.CLARIFY.value
    assert result["abstained"] is True
    assert result["abstention"]["abstention_mode"] == "clarify"
    assert "missing_amount" in result["abstention"]["kinds"]
    assert result["amount"] is None
    assert result.get("complaint_id") is None  # no case created when abstaining/clarifying
    assert result["clarification_prompts"]


def test_graph_does_not_invent_fraud_label():
    before_amount = None
    result = run_dispute_graph(
        {
            "text": "No reconozco un cargo",
            "language": "es",
            "amount": before_amount,
        }
    )
    assert result["decision"] == Decision.CLARIFY.value
    assert result.get("is_fraud") is None
    assert result.get("fraud_score") is None


def test_api_triage_returns_abstention_payload():
    response = client.post(
        "/disputes/triage",
        json={
            "text": "Acho que cobraram algo que não reconheço, mas não tenho o valor",
            "language": "pt",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "clarify"
    assert body["abstained"] is True
    assert body["abstention"]["is_ambiguous"] is True
    assert body["clarification_prompts"]
    assert set(FORBIDDEN_INVENTIONS).issubset(set(body["abstention"]["forbidden_inventions"]))


def test_clear_fraud_still_auto_resolves_when_facts_present():
    result = run_dispute_graph(
        {
            "text": "No reconozco un cargo de 45.51 USD en Empresa Telefonica",
            "language": "es",
            "amount": 45.51,
            "currency": "USD",
            "transaction_id": "TRX-CLEAR-1",
            "merchant_name": "Empresa Telefonica",
            "transaction_date": "2023-06-21",
            "is_fraud": True,
            "fraud_score": 97.45,
            "priority": "Medium",
        }
    )
    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result.get("abstained") in (False, None) or result["abstention"] is None or (
        result["abstention"] and result["abstention"].get("is_ambiguous") is False
    )
