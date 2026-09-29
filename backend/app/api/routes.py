"""HTTP API routes for the dispute triage service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.contracts.handoff import (
    SCHEMA_VERSION,
    HumanHandoff,
    build_example_handoff,
    handoff_json_schema,
)
from app.graph.runner import run_dispute_graph

router = APIRouter()


class DisputeRequest(BaseModel):
    """Minimal intake payload — expand in later sprint stories."""

    text: str = Field(..., min_length=1, description="Customer dispute in natural language (ES/PT)")
    language: str | None = Field(default=None, description="Optional language hint: es | pt")
    customer_id: str | None = None
    transaction_id: str | None = None


class DisputeResponse(BaseModel):
    """Skeleton graph result — nodes are stubs until Sprint 2."""

    decision: str
    nodes_visited: list[str]
    state: dict


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe for frontend, compose, and deploy."""
    return {"status": "ok", "service": "dispute-triage"}


@router.get("/graph/nodes")
def list_graph_nodes() -> dict[str, list[str]]:
    """Expose the explicit state-graph contract for frontend/docs."""
    return {
        "pipeline": ["understand", "decide", "act", "verify", "escalate"],
        "decisions": ["auto_resolve", "clarify", "escalate"],
    }


@router.get("/contracts/human-handoff")
def human_handoff_contract() -> dict[str, Any]:
    """Machine-readable handoff contract for frontend and data-pipeline.

    Returns schema_version, JSON Schema, and a canonical example grounded in
    the human-required use case. Raw transcripts are intentionally excluded.
    """
    example = build_example_handoff()
    return {
        "schema_version": SCHEMA_VERSION,
        "content_type": "application/json",
        "forbidden_fields": [
            "raw_transcript",
            "full_text",
            "customer_text",
            "agent_text",
            "chain_of_thought",
        ],
        "json_schema": handoff_json_schema(),
        "example": example.model_dump(mode="json"),
    }


@router.get("/contracts/human-handoff/example", response_model=HumanHandoff)
def human_handoff_example() -> HumanHandoff:
    """Canonical HumanHandoff example (OpenAPI-typed)."""
    return build_example_handoff()


@router.post("/disputes/triage", response_model=DisputeResponse)
def triage_dispute(payload: DisputeRequest) -> DisputeResponse:
    """Run the stubbed graph end-to-end so local wiring can be verified."""
    result = run_dispute_graph(
        {
            "text": payload.text,
            "language": payload.language,
            "customer_id": payload.customer_id,
            "transaction_id": payload.transaction_id,
        }
    )
    return DisputeResponse(
        decision=str(result.get("decision", "clarify")),
        nodes_visited=list(result.get("nodes_visited", [])),
        state=result,
    )
