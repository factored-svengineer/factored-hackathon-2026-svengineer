"""End-to-end tests for understand → decide → act graph nodes."""

from __future__ import annotations

import pytest
from app.graph import google_extractor
from app.graph.extract import extract_entities
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
                "Transaction date: 29/09/2026.\n"
                "Merchant: Google Play"
            ),
            "language": "en",
        }
    )

    assert result["decision"] == Decision.CLARIFY.value
    assert result["merchant_name"] == "Google Play"
    assert result["amount"] == 45.51
    assert result["transaction_date"] == "2026-09-29"
    assert result["open_questions"][0]["field"] == "transaction_id"
    assert result["open_questions"][0]["prompt"] == (
        "What is the ID of the disputed transaction?"
    )
    assert "What is the exact amount" not in " ".join(result["clarification_prompts"])
    assert "What is the name of the merchant" not in " ".join(result["clarification_prompts"])


def test_graph_uses_english_for_english_chat_requests():
    result = run_dispute_graph(
        {"text": "No reconozco un cargo", "language": "en"}
    )

    assert result["decision"] == Decision.CLARIFY.value
    assert result["clarification_prompts"] == [
        "What is the ID of the disputed transaction?"
    ]
    assert all(question["language"] == "en" for question in result["open_questions"])


def test_graph_defaults_to_english_when_language_is_missing():
    result = run_dispute_graph({"text": "I dispute an unknown charge"})

    assert result["decision"] == Decision.CLARIFY.value
    assert result["clarification_prompts"] == [
        "What is the ID of the disputed transaction?"
    ]
    assert all(question["language"] == "en" for question in result["open_questions"])


def test_extract_entities_pt():
    entities = extract_entities(
        "Não reconheço uma compra de R$120,00 no Mercado Livre em 5 de abril."
    )
    assert entities.amount == 120.0
    assert entities.currency == "BRL"
    assert entities.language_hint == "pt"


def test_graph_clarify_when_info_missing():
    result = run_dispute_graph(
        {"text": "Creo que me cobraron algo raro pero no recuerdo el monto", "language": "es"}
    )
    assert result["decision"] == Decision.CLARIFY.value
    assert result["understood"] is False or result.get("amount") is None
    assert result["clarification_prompts"]
    assert result["verified"] is True
    assert "escalate" not in result["nodes_visited"]


def test_graph_auto_resolve_clear_fraud(monkeypatch):
    transaction_id = "TRX-VV2MMGPU6842YMOC1BHN"
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CLI-1",
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
            "text": f"No reconozco un cargo de 45.51 USD en Empresa Telefonica {transaction_id}",
            "language": "es",
        }
    )
    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["complaint_id"]
    assert get_dispute_case(result["complaint_id"]) is not None
    assert result["verified"] is True
    assert result["verified_transaction"]["is_fraud"] is True
    assert "classified_category" not in result


def test_spanish_unknown_transaction_with_verified_fraud_auto_resolves(monkeypatch):
    transaction_id = "TRX-DDUE4JJQVQ5CIN8856QI"
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CLI-JP52WOIS6RWO",
            "amount": 113.94,
            "currency": "USD",
            "amount_usd": None,
            "merchant_name": "Laboratorio Central",
            "transaction_date": "2026-06-12 01:27:38",
            "transaction_status": "Approved",
            "is_fraud": True,
            "fraud_score": 95.1,
        },
    )

    result = run_dispute_graph(
        {
            "text": (
                "Quiero denunciar esta transaccion desconocida. El cargo fue USD "
                "113.94 en Laboratorio Central el día 2026-06-12. La ID de la "
                f"transacción es: {transaction_id}."
            ),
            "language": "es",
        }
    )

    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["verified_transaction"]["is_fraud"] is True
    assert "classified_category" not in result
    assert result["abstention"] is None


def test_transaction_id_not_found_escalates_to_human():
    transaction_id = "TRX-NOT-IN-RECORDS"
    result = run_dispute_graph(
        {
            "text": (
                "No reconozco un cargo de USD 45.51 en Empresa Telefonica "
                f"el 2026-06-12. ID: {transaction_id}"
            ),
            "language": "es",
        }
    )

    assert result["decision"] == Decision.ESCALATE.value
    assert result["transaction_lookup_not_found"] is True
    assert result["complaint_id"]
    assert result["verified"] is True
    assert result["handoff"]["reason"] == (
        "Provided transaction ID was not found in available records"
    )
    assert result["handoff"]["open_questions"][0]["field"] == "transaction_id_not_found"
    assert "no aparece" in result["handoff"]["open_questions"][0]["prompt"]


def test_structured_transaction_id_skips_gemini(monkeypatch):
    transaction_id = "TRX-DDUE4JJQVQ5CIN8856QI"
    monkeypatch.setattr(
        google_extractor,
        "extract_entities_with_google",
        lambda *_args, **_kwargs: pytest.fail(
            "A structured transaction ID must bypass Gemini extraction."
        ),
    )
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda found_id, _date=None: {
            "transaction_id": found_id,
            "customer_id": "CLI-1",
            "amount": 113.94,
            "currency": "USD",
            "amount_usd": 113.94,
            "merchant_name": "Laboratorio Central",
            "transaction_date": "2026-06-12",
            "transaction_status": "Approved",
            "is_fraud": True,
            "fraud_score": 95.1,
        },
    )

    result = run_dispute_graph(
        {
            "text": f"ID de transacción: {transaction_id}",
            "language": "es",
            "transaction_id": transaction_id,
            "amount": 113.94,
            "currency": "USD",
            "merchant_name": "Laboratorio Central",
            "transaction_date": "2026-06-12",
        }
    )

    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["transaction_id"] == transaction_id
    assert result["verified_transaction"]["is_fraud"] is True


def test_graph_pauses_automatic_resolution_until_user_approves(monkeypatch):
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _date=None: None,
    )
    result = run_dispute_graph(
        {
            "text": "Fraudulent charge",
            "amount": 113.94,
            "currency": "USD",
            "merchant_name": "Merchant",
            "transaction_date": "2026-06-12",
            "is_fraud": True,
            "fraud_score": 95.1,
            "require_approval": True,
        }
    )

    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["approval_required"] is True
    assert result["nodes_visited"] == ["understand", "decide"]
    assert result.get("complaint_id") is None


def test_graph_continues_after_approval_for_same_decision(monkeypatch):
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _date=None: None,
    )
    result = run_dispute_graph(
        {
            "text": "Fraudulent charge",
            "amount": 113.94,
            "currency": "USD",
            "merchant_name": "Merchant",
            "transaction_date": "2026-06-12",
            "is_fraud": True,
            "fraud_score": 95.1,
            "require_approval": True,
            "approval_granted": True,
            "approval_decision": "auto_resolve",
        }
    )

    assert result["decision"] == Decision.AUTO_RESOLVE.value
    assert result["approval_required"] is False
    assert result["complaint_id"]
    assert result["verified"] is True


def test_graph_reasks_approval_if_decision_changes(monkeypatch):
    transaction_id = "TRX-DDUE4JJQVQ5CIN8856QI"
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda found_id, _date=None: {
            "transaction_id": found_id,
            "customer_id": "CLI-1",
            "amount": 113.94,
            "currency": "USD",
            "amount_usd": 113.94,
            "merchant_name": "Laboratorio Central",
            "transaction_date": "2026-06-12",
            "transaction_status": "Approved",
            "is_fraud": False,
            "fraud_score": 27.19,
        },
    )
    result = run_dispute_graph(
        {
            "text": "Fraudulent charge",
            "transaction_id": transaction_id,
            "amount": 113.94,
            "currency": "USD",
            "is_fraud": True,
            "fraud_score": 95.1,
            "require_approval": True,
            "approval_granted": True,
            "approval_decision": "auto_resolve",
        }
    )

    assert result["decision"] == Decision.ESCALATE.value
    assert result["approval_required"] is True
    assert result["approval_decision"] == Decision.ESCALATE.value
    assert result.get("complaint_id") is None


def test_transaction_lookup_failure_escalates_with_human_verification(monkeypatch):
    transaction_id = "TRX-LOOKUP-UNAVAILABLE"

    def fail_lookup(_transaction_id, _transaction_date=None):
        raise RuntimeError("transaction data source unavailable")

    monkeypatch.setattr("app.tools.data.get_transaction", fail_lookup)
    result = run_dispute_graph(
        {
            "text": f"Disputo el cargo de USD 45.51. ID: {transaction_id}",
            "language": "es",
        }
    )

    assert result["decision"] == Decision.ESCALATE.value
    assert result["transaction_lookup_failed"] is True
    assert result["transaction_lookup_not_found"] is False
    assert result["handoff"]["reason"] == (
        "Transaction lookup failed; human verification is required"
    )
    assert result["handoff"]["open_questions"][0]["field"] == (
        "transaction_lookup_failed"
    )


def test_customer_without_transaction_id_escalates_to_human(monkeypatch):
    monkeypatch.setattr(
        google_extractor,
        "extract_entities_with_google",
        lambda *_args, **_kwargs: pytest.fail(
            "Do not call Gemini when the customer confirms they do not have an ID."
        ),
    )
    result = run_dispute_graph(
        {
            "text": "No tengo el ID de la transacción.",
            "language": "es",
            "transaction_id_unavailable": True,
            "amount": 45.51,
            "currency": "USD",
            "merchant_name": "Tienda",
            "transaction_date": "2026-06-12",
        }
    )

    assert result["decision"] == Decision.ESCALATE.value
    assert result["handoff"]["reason"] == (
        "Customer does not have the transaction ID; human assistance is required"
    )
    assert result["handoff"]["open_questions"][0]["field"] == (
        "transaction_id_unavailable"
    )
    assert result["handoff"]["open_questions"][0]["language"] == "es"
    assert result["handoff"]["case"]["claimed_amount"] == 45.51


def test_triage_rejects_transaction_id_outside_database_format():
    response = client.post(
        "/disputes/triage",
        json={"text": "ID: TRX-TOO-SHORT", "transaction_id": "TRX-TOO-SHORT"},
    )

    assert response.status_code == 422


def test_triage_normalizes_valid_transaction_id_before_lookup(monkeypatch):
    requested_ids = []
    transaction_id = "TRX-DDUE4JJQVQ5CIN8856QI"
    monkeypatch.setattr(
        google_extractor,
        "extract_entities_with_google",
        lambda *_args, **_kwargs: pytest.fail(
            "A structured transaction ID must bypass Gemini extraction."
        ),
    )
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda found_id, _date=None: requested_ids.append(found_id)
        or {
            "transaction_id": found_id,
            "customer_id": "CLI-1",
            "amount": 113.94,
            "currency": "USD",
            "amount_usd": 113.94,
            "merchant_name": "Laboratorio Central",
            "transaction_date": "2026-06-12",
            "transaction_status": "Approved",
            "is_fraud": True,
            "fraud_score": 95.1,
        },
    )

    payload = {
        "text": "ID de transacción",
        "transaction_id": transaction_id.lower(),
        "require_approval": True,
    }
    preview = client.post(
        "/disputes/triage",
        json=payload,
    )

    assert preview.status_code == 200
    assert preview.json()["state"]["approval_required"] is True
    assert preview.json()["state"].get("complaint_id") is None

    response = client.post(
        "/disputes/triage",
        json={
            **payload,
            "approval_granted": True,
            "approval_decision": Decision.AUTO_RESOLVE.value,
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == Decision.AUTO_RESOLVE.value
    assert response.json()["state"]["verified"] is True
    assert requested_ids == [transaction_id, transaction_id]


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
    assert result["handoff"]["classified_category"]["category"] == "unknown"
    assert result["verified"] is True


def test_api_escalates_when_customer_cannot_provide_verification_evidence(monkeypatch):
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CLI-1",
            "amount": 45.51,
            "currency": "USD",
            "amount_usd": 45.51,
            "merchant_name": "Google Play",
            "transaction_date": "2026-09-29",
            "transaction_status": "Approved",
            "is_fraud": None,
            "fraud_score": None,
        },
    )
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
            "transaction_id": "TRX-EXAMPLE0000000000000",
            "approval_granted": True,
            "approval_decision": Decision.ESCALATE.value,
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


def test_api_triage_clear_fraud(monkeypatch):
    transaction_id = "TRX-TESTCLEARFRAUD000001"
    monkeypatch.setattr(
        "app.tools.data.get_transaction",
        lambda _transaction_id, _transaction_date=None: {
            "transaction_id": transaction_id,
            "customer_id": "CLI-1",
            "amount": 45.51,
            "currency": "USD",
            "amount_usd": 45.51,
            "merchant_name": "Empresa Telefonica",
            "transaction_date": "2026-06-12",
            "transaction_status": "Approved",
            "is_fraud": True,
            "fraud_score": 97.45,
        },
    )
    response = client.post(
        "/disputes/triage",
        json={
            "text": "No reconozco un cargo de 45.51 USD",
            "language": "es",
            "is_fraud": True,
            "fraud_score": 97.45,
            "transaction_id": transaction_id,
            "amount": 45.51,
            "currency": "USD",
            "merchant_name": "Empresa Telefonica",
            "approval_granted": True,
            "approval_decision": Decision.AUTO_RESOLVE.value,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "auto_resolve"
    assert body["state"]["verified"] is True
    assert body["state"]["complaint_id"]
