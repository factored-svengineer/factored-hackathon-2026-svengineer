"""HTTP API routes for the dispute triage service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.contracts.handoff import (
    SCHEMA_VERSION,
    HumanHandoff,
    build_example_handoff,
    handoff_json_schema,
)
from app.graph.google_extractor import (
    GoogleAIStudioConfigurationError,
    GoogleAIStudioExtractionError,
    GoogleAIStudioQuotaError,
)
from app.graph.runner import run_dispute_graph
from app.policy.rules import DEFAULT_POLICY, evaluate_dispute, load_policy_config
from app.tools.aws_data import S3ConfigurationError, S3LookupError

router = APIRouter()


class DisputeRequest(BaseModel):
    """Minimal intake payload — expand in later sprint stories."""

    text: str = Field(..., min_length=1, description="Customer dispute in natural language (ES/PT)")
    language: str | None = Field(default=None, description="Optional language hint: es | pt")
    customer_id: str | None = None
    transaction_id: str | None = None
    # Optional structured signals so /disputes/triage can exercise policy early.
    amount: float | None = None
    currency: str | None = None
    is_fraud: bool | None = None
    fraud_score: float | None = None
    priority: str | None = None
    sla_breached: bool | None = None
    verification_evidence_unavailable: bool = False
    status: str | None = None
    merchant_name: str | None = None
    transaction_date: str | None = None


class PolicyEvaluateRequest(BaseModel):
    """Inputs for the deterministic policy layer (no LLM)."""

    amount: float | None = None
    currency: str | None = None
    is_fraud: bool | None = None
    fraud_score: float | None = Field(
        default=None,
        description="Raw (0–100) or normalized (0–1) fraud score; policy normalizes",
    )
    priority: str | None = None
    sla_breached: bool | None = None
    sla_hours_remaining: float | None = None
    status: str | None = None
    transaction_id: str | None = None
    merchant_name: str | None = None
    transaction_date: str | None = None


class DisputeResponse(BaseModel):
    """Triage result including explicit abstention when the case is ambiguous."""

    decision: str
    nodes_visited: list[str]
    abstained: bool = False
    abstention: dict[str, Any] | None = None
    clarification_prompts: list[str] = Field(default_factory=list)
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


@router.get("/policy/config")
def policy_config() -> dict[str, Any]:
    """Expose active deterministic thresholds (LLM must not invent these)."""
    cfg = load_policy_config()
    return {
        "high_amount_usd": cfg.high_amount_usd,
        "escalate_amount_usd": cfg.escalate_amount_usd,
        "fraud_score_auto_resolve": cfg.fraud_score_auto_resolve,
        "fraud_score_ambiguous_low": cfg.fraud_score_ambiguous_low,
        "fraud_score_ambiguous_high": cfg.fraud_score_ambiguous_high,
        "fraud_score_raw_threshold": cfg.fraud_score_raw_threshold,
        "sla_hours_high_priority": cfg.sla_hours_high_priority,
        "sla_hours_default": cfg.sla_hours_default,
        "required_fields_for_resolve": list(cfg.required_fields_for_resolve),
        "defaults_equal_runtime": cfg == DEFAULT_POLICY,
    }


@router.post("/policy/evaluate")
def policy_evaluate(payload: PolicyEvaluateRequest) -> dict[str, Any]:
    """Run deterministic triage policy and return decision + reasons."""
    result = evaluate_dispute(
        amount=payload.amount,
        currency=payload.currency,
        is_fraud=payload.is_fraud,
        fraud_score=payload.fraud_score,
        priority=payload.priority,
        sla_breached=payload.sla_breached,
        sla_hours_remaining=payload.sla_hours_remaining,
        status=payload.status,
        transaction_id=payload.transaction_id,
        merchant_name=payload.merchant_name,
        transaction_date=payload.transaction_date,
    )
    return result.to_dict()


@router.post("/disputes/triage", response_model=DisputeResponse)
def triage_dispute(payload: DisputeRequest) -> DisputeResponse:
    """Extract customer-provided facts, then apply deterministic triage policy."""
    try:
        result = run_dispute_graph(
            {
                "text": payload.text,
                "language": payload.language,
                "customer_id": payload.customer_id,
                "transaction_id": payload.transaction_id,
                "amount": payload.amount,
                "currency": payload.currency,
                "is_fraud": payload.is_fraud,
                "fraud_score": payload.fraud_score,
                "priority": payload.priority,
                "sla_breached": payload.sla_breached,
                "verification_evidence_unavailable": payload.verification_evidence_unavailable,
                "status": "Escalated" if payload.verification_evidence_unavailable else payload.status,
                "merchant_name": payload.merchant_name,
                "transaction_date": payload.transaction_date,
            }
        )
    except GoogleAIStudioConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GoogleAIStudioQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except GoogleAIStudioExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except S3ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except S3LookupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DisputeResponse(
        decision=str(result.get("decision", "clarify")),
        nodes_visited=list(result.get("nodes_visited", [])),
        abstained=bool(result.get("abstained")),
        abstention=result.get("abstention"),
        clarification_prompts=list(result.get("clarification_prompts") or []),
        state=result,
    )
