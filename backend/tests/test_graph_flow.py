"""End-to-end tests for understand → decide → act graph nodes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.graph.extract import classify_from_text, extract_entities
from app.graph.nodes import Decision
from app.graph.runner import run_dispute_graph
from app.main import app
from app.tools.store import clear_dispute_cases, get_dispute_case

client = TestClient(app)


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
