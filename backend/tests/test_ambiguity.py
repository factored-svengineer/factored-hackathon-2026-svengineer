"""Tests for explicit ambiguity / abstention (Issue #9)."""

from __future__ import annotations

import pytest
from app.graph import google_extractor
from app.graph.ambiguity import (
    FORBIDDEN_INVENTIONS,
    AbstentionMode,
    AmbiguityKind,
    assess_ambiguity,
)
from app.graph.extract import ExtractedEntities, extract_entities
from app.graph.nodes import Decision
from app.graph.runner import run_dispute_graph
from app.main import app
from app.tools.store import clear_dispute_cases
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def use_deterministic_extractor_for_graph_tests(monkeypatch):
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


def test_assess_missing_amount_date_merchant():
    result = assess_ambiguity(
        amount=None,
        transaction_id=None,
        merchant_name=None,
        transaction_date=None,
    )
    assert result.is_ambiguous is True
    assert result.abstention_mode == AbstentionMode.CLARIFY
    assert AmbiguityKind.MISSING_AMOUNT in result.kinds
    assert AmbiguityKind.MISSING_TRANSACTION_REF in result.kinds
    assert "amount" in result.forbidden_inventions


def test_transaction_id_is_sufficient_without_merchant_or_date():
    result = assess_ambiguity(
        amount=343.03,
        transaction_id="TRX-1",
        merchant_name=None,
        transaction_date=None,
    )

    assert result.is_ambiguous is False
    assert AmbiguityKind.MISSING_MERCHANT not in result.kinds
    assert AmbiguityKind.MISSING_DATE not in result.kinds
    assert AmbiguityKind.MISSING_TRANSACTION_REF not in result.kinds


def test_verified_non_fraud_transaction_escalates_without_asking_for_merchant(
    monkeypatch,
):
    transaction_id = "TRX-1"

    def fake_extractor(_text, **_kwargs):
        return ExtractedEntities(
            amount=None,
            currency=None,
            transaction_date="2026-06-17",
            merchant_name=None,
            transaction_id=transaction_id,
            language_hint="en",
        )

    monkeypatch.setattr(
        google_extractor,
        "extract_entities_with_google",
        fake_extractor,
    )
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CUST-1",
            "amount": 343.03,
            "currency": "USD",
            "amount_usd": 343.03,
            "merchant_name": "",
            "transaction_date": "2026-06-17 19:51:02",
            "transaction_status": "Approved",
            "is_fraud": False,
            "fraud_score": 27.19,
        },
    )

    result = run_dispute_graph(
        {
            "text": (
                "Please help me dispute an unrecognized transaction. "
                "The transaction ID is TRX-1 and the transaction date is 2026-06-17."
            ),
            "language": "en",
            "is_fraud": True,
            "fraud_score": 97.45,
        }
    )

    assert result["decision"] == Decision.ESCALATE.value
    assert result["verified_transaction"]["transaction_id"] == transaction_id
    assert result["merchant_name"] == ""
    assert result["escalate_reason"] == (
        "Verified transaction has a low fraud signal; human review is required"
    )
    assert result["handoff"]["verified_transaction"]["transaction_id"] == transaction_id
    assert all("merchant" not in prompt.lower() for prompt in result["clarification_prompts"])


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


def test_clear_fraud_still_auto_resolves_when_facts_present(monkeypatch):
    transaction_id = "TRX-CLEAR-1"
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CUST-CLEAR",
            "amount": 45.51,
            "currency": "USD",
            "amount_usd": 45.51,
            "merchant_name": "Empresa Telefonica",
            "transaction_date": "2023-06-21",
            "transaction_status": "Approved",
            "is_fraud": True,
            "fraud_score": 97.45,
        },
    )
    result = run_dispute_graph(
        {
            "text": "No reconozco un cargo de 45.51 USD en Empresa Telefonica",
            "language": "es",
            "amount": 45.51,
            "currency": "USD",
            "transaction_id": transaction_id,
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
