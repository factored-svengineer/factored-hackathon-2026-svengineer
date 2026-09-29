"""Explicit state-graph nodes for dispute processing.

Pipeline: understand → decide → act → verify → escalate
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class GraphNode(str, Enum):
    UNDERSTAND = "understand"
    DECIDE = "decide"
    ACT = "act"
    VERIFY = "verify"
    ESCALATE = "escalate"


class Decision(str, Enum):
    AUTO_RESOLVE = "auto_resolve"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


def understand(state: dict[str, Any]) -> dict[str, Any]:
    """Parse natural-language dispute (ES/PT) and extract entities."""
    # TODO: LLM/NER extraction of amount, date, merchant, category hints
    return {**state, "node": GraphNode.UNDERSTAND, "understood": False}


def decide(state: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic policies + fraud signals to choose next action."""
    # TODO: call policy layer + classifier + fraud checks
    return {**state, "node": GraphNode.DECIDE, "decision": Decision.CLARIFY}


def act(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the chosen action (create dispute case, request clarification, etc.)."""
    # TODO: invoke tools to mutate external systems
    return {**state, "node": GraphNode.ACT, "actions_taken": []}


def verify(state: dict[str, Any]) -> dict[str, Any]:
    """Confirm that side-effects (e.g. dispute case created) actually persisted."""
    # TODO: re-read source of truth and set verified flag
    return {**state, "node": GraphNode.VERIFY, "verified": False}


def escalate(state: dict[str, Any]) -> dict[str, Any]:
    """Build structured human handoff — never raw transcript."""
    from app.contracts.handoff import (
        CaseContext,
        ClassifiedCategory,
        HumanHandoff,
        VerifiedTransaction,
        new_handoff_id,
        utc_now_iso,
    )

    existing = state.get("handoff")
    if isinstance(existing, HumanHandoff):
        handoff = existing
    elif isinstance(existing, dict) and existing.get("schema_version"):
        handoff = HumanHandoff.model_validate(existing)
    else:
        category = state.get("classified_category")
        if isinstance(category, ClassifiedCategory):
            classified = category
        elif isinstance(category, dict):
            classified = ClassifiedCategory.model_validate(category)
        else:
            classified = ClassifiedCategory(category="unknown")

        txn = state.get("verified_transaction")
        if isinstance(txn, dict):
            txn = VerifiedTransaction.model_validate(txn)

        case = state.get("case")
        if isinstance(case, dict):
            case_ctx = CaseContext.model_validate(case)
        else:
            case_ctx = CaseContext(
                complaint_id=state.get("complaint_id"),
                customer_id=state.get("customer_id"),
                language=state.get("language"),
                priority=state.get("priority"),
                sla_breached=state.get("sla_breached"),
                claimed_amount=state.get("claimed_amount"),
                currency=state.get("currency"),
            )

        handoff = HumanHandoff(
            handoff_id=new_handoff_id(),
            created_at=utc_now_iso(),
            reason=str(state.get("escalate_reason") or "graph_decision=escalate"),
            case=case_ctx,
            verified_transaction=txn,
            classified_category=classified,
            fraud_score=state.get("fraud_score"),
            actions_taken=list(state.get("actions_taken") or []),
            open_questions=list(state.get("open_questions") or []),
            support_evidence=list(state.get("support_evidence") or []),
        )

    return {
        **state,
        "node": GraphNode.ESCALATE,
        "handoff": handoff.model_dump(mode="json"),
    }
