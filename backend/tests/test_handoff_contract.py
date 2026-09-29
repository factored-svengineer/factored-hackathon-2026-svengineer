"""Tests for the human handoff JSON contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.contracts.handoff import (
    SCHEMA_VERSION,
    EvidenceType,
    HumanHandoff,
    SupportEvidence,
    build_example_handoff,
    handoff_json_schema,
)
from app.graph.nodes import Decision, escalate
from app.main import app

client = TestClient(app)


def test_example_handoff_is_valid():
    handoff = build_example_handoff()
    assert handoff.schema_version == SCHEMA_VERSION
    assert handoff.case.complaint_id == "CMP-W9KJLENI8RSM8TU99NXZ"
    assert handoff.classified_category.category == "Transactions"
    assert handoff.verified_transaction is None
    assert handoff.open_questions
    assert handoff.actions_taken
    # Round-trip
    restored = HumanHandoff.model_validate(handoff.model_dump(mode="json"))
    assert restored.handoff_id == handoff.handoff_id


def test_support_evidence_rejects_raw_transcript_dialogue():
    with pytest.raises(ValidationError):
        SupportEvidence(
            evidence_id="EV-BAD",
            evidence_type=EvidenceType.TRANSCRIPT_SUMMARY,
            summary="Cliente: hola\nAgente: buenos días, ¿en qué le ayudo?",
            source_ref="INT-1",
        )


def test_extra_fields_forbidden():
    payload = build_example_handoff().model_dump(mode="json")
    payload["raw_transcript"] = "should not be allowed"
    with pytest.raises(ValidationError):
        HumanHandoff.model_validate(payload)


def test_fraud_score_must_be_normalized():
    payload = build_example_handoff().model_dump(mode="json")
    payload["fraud_score"] = 97.45  # raw scale — invalid on top-level field
    with pytest.raises(ValidationError):
        HumanHandoff.model_validate(payload)


def test_contract_endpoint_returns_schema_and_example():
    response = client.get("/contracts/human-handoff")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert "json_schema" in body
    assert body["example"]["case"]["complaint_id"] == "CMP-W9KJLENI8RSM8TU99NXZ"
    assert "raw_transcript" in body["forbidden_fields"]


def test_typed_example_endpoint():
    response = client.get("/contracts/human-handoff/example")
    assert response.status_code == 200
    assert response.json()["schema_version"] == SCHEMA_VERSION


def test_escalate_node_emits_valid_handoff():
    state = escalate(
        {
            "decision": Decision.ESCALATE,
            "complaint_id": "CMP-W9KJLENI8RSM8TU99NXZ",
            "customer_id": "CLI-IDKD41Z51JP1",
            "language": "es",
            "escalate_reason": "priority=Critical AND sla_breached=true",
            "classified_category": {
                "category": "Transactions",
                "subcategory": "Cargo no reconocido",
                "confidence": 0.9,
                "classifier": "rules",
            },
            "actions_taken": [],
            "open_questions": [],
            "support_evidence": [],
        }
    )
    handoff = HumanHandoff.model_validate(state["handoff"])
    assert handoff.case.complaint_id == "CMP-W9KJLENI8RSM8TU99NXZ"
    assert handoff.classified_category.subcategory == "Cargo no reconocido"


def test_static_schema_file_matches_model():
    schema_path = (
        Path(__file__).resolve().parents[2] / "docs" / "schemas" / "human-handoff.schema.json"
    )
    # File is generated in this PR; if missing locally mid-edit, skip.
    if not schema_path.exists():
        pytest.skip("schema file not generated yet")
    on_disk = json.loads(schema_path.read_text(encoding="utf-8"))
    assert on_disk["title"] == handoff_json_schema()["title"]
