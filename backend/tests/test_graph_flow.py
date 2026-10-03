"""End-to-end tests for understand → decide → act graph nodes."""

from __future__ import annotations

import pytest
from app.graph import google_extractor
from app.graph.extract import classify_from_text, extract_entities
from app.graph.nodes import Decision
from app.graph.runner import run_dispute_graph
from app.main import app
from app.tools.store import clear_dispute_cases, get_dispute_case
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


def test_extract_entities_es_amount_and_merchant():
    entities = extract_entities(
        "No reconozco un cargo de $45.99 en Amazon del 12 de marzo."
    )
    assert entities.amount == 45.99
    assert entities.currency == "USD"
    assert entities.merchant_name and "Amazon" in entities.merchant_name
    assert entities.transaction_date == "2026-03-12"
    assert entities.language_hint == "es"


def test_extract_entities_labeled_merchant_does_not_consume_next_sentence():
    entities = extract_entities(
        "I dispute an unauthorized charge of USD 45.51. Merchant: Google Play. "
        "Transaction date: 29/09/2026. Transaction ID: TRX-EXAMPLE0001."
    )

    assert entities.amount == 45.51
    assert entities.currency == "USD"
    assert entities.transaction_date == "2026-09-29"
    assert entities.merchant_name == "Google Play"
    assert entities.transaction_id == "TRX-EXAMPLE0001"


def test_graph_retains_complete_facts_and_only_asks_for_verification():
    result = run_dispute_graph(
        {
            "text": (
                "I dispute an unauthorized charge of USD 45.51. Merchant: Google Play. "
                "Transaction date: 29/09/2026. Transaction ID: TRX-EXAMPLE0001.\n"
                "Merchant: Google Play"
            ),
            "language": "en",
        }
    )

    assert result["decision"] == Decision.CLARIFY.value
    assert result["merchant_name"] == "Google Play"
    assert result["amount"] == 45.51
    assert result["transaction_date"] == "2026-09-29"
    assert result["transaction_id"] == "TRX-EXAMPLE0001"
    assert result["open_questions"][0]["field"] == "verification_evidence"
    assert "What is the exact amount" not in " ".join(result["clarification_prompts"])
    assert "What is the name of the merchant" not in " ".join(result["clarification_prompts"])


def test_graph_uses_english_for_english_chat_requests():
    result = run_dispute_graph(
        {"text": "No reconozco un cargo", "language": "en"}
    )

    assert result["decision"] == Decision.CLARIFY.value
    assert result["clarification_prompts"][0].startswith(
        "To continue without guessing, we need:"
    )
    assert "What is the exact amount of the charge you are disputing?" in result[
        "clarification_prompts"
    ]
    assert all(question["language"] == "en" for question in result["open_questions"])


def test_graph_defaults_to_english_when_language_is_missing():
    result = run_dispute_graph({"text": "I dispute an unknown charge"})

    assert result["decision"] == Decision.CLARIFY.value
    assert result["clarification_prompts"][0].startswith(
        "To continue without guessing, we need:"
    )
    assert all(question["language"] == "en" for question in result["open_questions"])


def test_extract_entities_pt():
    entities = extract_entities(
        "Não reconheço uma compra de R$120,00 no Mercado Livre em 5 de abril."
    )
    assert entities.amount == 120.0
    assert entities.currency == "BRL"
    assert entities.language_hint == "pt"


def test_classify_unrecognized_charge():
    result = classify_from_text("No reconozco un cargo, parece fraude")
    assert result["category"] == "Transactions"
    assert result["subcategory"] == "Cargo no reconocido"


def test_graph_clarify_when_info_missing():
    result = run_dispute_graph(
        {"text": "Creo que me cobraron algo raro pero no recuerdo el monto", "language": "es"}
    )
    assert result["decision"] == Decision.CLARIFY.value
    assert result["understood"] is False or result.get("amount") is None
    assert result["clarification_prompts"]
    assert result["verified"] is True
    assert "escalate" not in result["nodes_visited"]


def test_graph_auto_resolve_clear_fraud():
    result = run_dispute_graph(
        {
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
    )
    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["complaint_id"]
    assert get_dispute_case(result["complaint_id"]) is not None
    assert result["verified"] is True
    assert result["classified_category"]["subcategory"] == "Cargo no reconocido"


def test_transaction_lookup_autocompletes_missing_case_fields(monkeypatch):
    transaction_id = "TRX-LOOKUP-AUTOFILL"
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CLI-LOOKUP-1",
            "amount": 45.51,
            "currency": "USD",
            "amount_usd": 45.51,
            "merchant_name": "Empresa Telefonica",
            "transaction_date": "2026-06-12 01:27:38",
            "transaction_status": "Approved",
            "is_fraud": True,
            "fraud_score": 97.45,
        },
    )

    result = run_dispute_graph(
        {
            "text": "No reconozco este cargo",
            "language": "es",
            "transaction_id": transaction_id,
        }
    )

    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["amount"] == 45.51
    assert result["currency"] == "USD"
    assert result["merchant_name"] == "Empresa Telefonica"
    assert result["transaction_date"] == "2026-06-12 01:27:38"
    assert result["customer_id"] == "CLI-LOOKUP-1"
    case = get_dispute_case(result["complaint_id"])
    assert case["claimed_amount"] == 45.51
    assert case["currency"] == "USD"
    assert case["customer_id"] == "CLI-LOOKUP-1"


def test_denied_transaction_is_not_auto_resolved_or_created_as_refund_case(
    monkeypatch,
):
    transaction_id = "TRX-DECLINED-1"
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CLI-DENIED-1",
            "amount": 45.51,
            "currency": "USD",
            "amount_usd": 45.51,
            "merchant_name": "Empresa Telefonica",
            "transaction_date": "2026-06-12 01:27:38",
            "transaction_status": "Denied",
            "is_fraud": True,
            "fraud_score": 97.45,
        },
    )

    result = run_dispute_graph(
        {
            "text": "No reconozco este cargo",
            "language": "es",
            "transaction_id": transaction_id,
        }
    )

    assert result["decision"] == Decision.CLARIFY.value
    assert result["verified_transaction"]["transaction_status"] == "Denied"
    assert result.get("complaint_id") is None
    assert result["clarification_prompts"]
    assert any("no hay un cargo completado que reembolsar" in prompt for prompt in result["clarification_prompts"])
    assert "escalate" not in result["nodes_visited"]


def test_graph_escalate_human_required():
    result = run_dispute_graph(
        {
            "text": "Disputo un cargo no reconocido de 2984.58 COP, caso critico",
            "language": "es",
            "amount": 2984.58,
            "currency": "COP",
            "priority": "Critical",
            "status": "Escalated",
            "sla_breached": True,
            "customer_id": "CLI-IDKD41Z51JP1",
        }
    )
    assert result["decision"] == Decision.ESCALATE.value
    assert "escalate" in result["nodes_visited"]
    assert result["handoff"]["case"]["complaint_id"] == result["complaint_id"]
    assert result["handoff"]["classified_category"]["category"] == "Transactions"
    assert result["verified"] is True


def test_api_escalates_when_customer_cannot_provide_verification_evidence():
    response = client.post(
        "/disputes/triage",
        json={
            "text": "I cannot provide a transaction record or statement.",
            "language": "en",
            "verification_evidence_unavailable": True,
            "amount": 45.51,
            "currency": "USD",
            "merchant_name": "Google Play",
            "transaction_date": "2026-09-29",
            "transaction_id": "TRX-EXAMPLE0001",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "escalate"
    assert body["state"]["handoff"]["reason"] == (
        "Customer cannot provide transaction verification evidence"
    )
    assert body["state"]["handoff"]["case"]["status"] == "Escalated"
    assert body["state"]["handoff"]["open_questions"][0]["field"] == (
        "verification_evidence"
    )


def test_api_triage_clear_fraud():
    response = client.post(
        "/disputes/triage",
        json={
            "text": "No reconozco un cargo de 45.51 USD",
            "language": "es",
            "is_fraud": True,
            "fraud_score": 97.45,
            "transaction_id": "TRX-TESTCLEARFRAUD001",
            "amount": 45.51,
            "currency": "USD",
            "merchant_name": "Empresa Telefonica",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "auto_resolve"
    assert body["state"]["verified"] is True
    assert body["state"]["complaint_id"]
