"""HTTP API routes for the dispute triage service."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

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
