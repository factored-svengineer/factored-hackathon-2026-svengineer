"""Unit tests for deterministic dispute policy."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.policy.rules import (
    PolicyDecision,
    evaluate_dispute,
    normalize_fraud_score,
)

client = TestClient(app)


def test_normalize_fraud_score_raw_and_unit():
    assert normalize_fraud_score(97.45) == 0.9745
    assert normalize_fraud_score(0.97) == 0.97
    assert normalize_fraud_score(None) is None


def test_clear_fraud_auto_resolve_archetype():
    """CMP-P7HVN55… + txn TRX-VV2MM… (is_fraud, score 97.45)."""
    result = evaluate_dispute(
        amount=45.51,
        currency="USD",
        is_fraud=True,
        fraud_score=97.45,
        priority="Medium",
        transaction_id="TRX-VV2MMGPU6842YMOC1BHN",
        merchant_name="Empresa Telefonica",
        sla_breached=False,
    )
    assert result.decision == PolicyDecision.AUTO_RESOLVE
    assert result.fraud_score_normalized == 0.9745
    assert any("is_fraud=true" in r for r in result.reasons)


def test_ambiguous_missing_amount_clarify_archetype():
    """CMP-UIWYTUU… — Cargo no reconocido sin monto."""
    result = evaluate_dispute(
        amount=None,
        is_fraud=None,
        fraud_score=None,
        priority="Low",
        transaction_id=None,
        sla_breached=False,
        status="Open",
    )
    assert result.decision == PolicyDecision.CLARIFY
    assert "amount" in result.missing_fields
    assert "transaction_ref" in result.missing_fields


def test_human_required_escalate_archetype():
    """CMP-W9KJLENI… — Critical + Escalated + SLA breach."""
    result = evaluate_dispute(
        amount=2984.58,
        currency="COP",
        priority="Critical",
        status="Escalated",
        sla_breached=True,
        transaction_id=None,
    )
    assert result.decision == PolicyDecision.ESCALATE
    assert "sla_breached=true" in result.reasons
    assert any("priority=" in r for r in result.reasons)


def test_escalate_beats_clear_fraud_when_sla_breached():
    result = evaluate_dispute(
        amount=100.0,
        is_fraud=True,
        fraud_score=0.99,
        priority="Medium",
        sla_breached=True,
        transaction_id="TRX-1",
    )
    assert result.decision == PolicyDecision.ESCALATE


def test_high_amount_escalates():
    result = evaluate_dispute(
        amount=6000.0,
        priority="Low",
        transaction_id="TRX-1",
        is_fraud=False,
        fraud_score=0.1,
    )
    assert result.decision == PolicyDecision.ESCALATE
    assert any("amount>=" in r for r in result.reasons)


def test_ambiguous_fraud_score_clarifies_when_not_labeled_fraud():
    result = evaluate_dispute(
        amount=200.0,
        is_fraud=False,
        fraud_score=55.0,  # → 0.55 grey zone
        priority="Low",
        transaction_id="TRX-1",
    )
    assert result.decision == PolicyDecision.CLARIFY
    assert any("fraud_score_ambiguous" in r for r in result.reasons)


def test_policy_config_endpoint():
    response = client.get("/policy/config")
    assert response.status_code == 200
    body = response.json()
    assert body["fraud_score_auto_resolve"] == 0.85
    assert body["escalate_amount_usd"] == 5000.0


def test_policy_evaluate_endpoint_human_case():
    response = client.post(
        "/policy/evaluate",
        json={
            "amount": 2984.58,
            "currency": "COP",
            "priority": "Critical",
            "status": "Escalated",
            "sla_breached": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "escalate"
    assert body["reasons"]
