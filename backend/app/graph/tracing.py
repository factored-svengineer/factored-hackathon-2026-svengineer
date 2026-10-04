"""Auditable execution tracing for dispute triage (Issue #14).

Explainability comes from recorded facts + deterministic business-rule reasons.
Gemini is used only for entity extraction; it never chooses auto_resolve /
clarify / escalate. Chain-of-thought and raw transcripts are forbidden.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from app.contracts.handoff import utc_now_iso

TRACE_SCHEMA_VERSION = "1.0.0"

# Roles make the LLM vs rules boundary explicit in every step.
ROLE_LLM_EXTRACTION = "llm_extraction"
ROLE_BUSINESS_RULES = "business_rules"
ROLE_TOOL = "tool"
ROLE_SYSTEM = "system"

FORBIDDEN_TRACE_FIELDS = (
    "chain_of_thought",
    "raw_transcript",
    "full_text",
    "customer_text",
    "agent_text",
    "llm_reasoning",
    "prompt",
    "completion",
)

logger = logging.getLogger("app.graph.trace")

EXPLAINABILITY_CONTRACT = {
    "principle": "rules_and_records_not_chain_of_thought",
    "llm_role": (
        "Gemini extracts explicitly stated transaction facts from customer text only. "
        "It does not decide auto_resolve, clarify, or escalate."
    ),
    "decision_role": (
        "Business policy, ambiguity rules, and tool outcomes determine the triage "
        "decision. No LLM/agent chooses the resolution path."
    ),
    "forbidden_fields": list(FORBIDDEN_TRACE_FIELDS),
}


def new_trace_id() -> str:
    return f"TRC-{uuid4().hex[:16].upper()}"


def start_execution_trace(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create an empty auditable trace attached to a run."""
    state = state or {}
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "trace_id": state.get("trace_id") or new_trace_id(),
        "started_at": utc_now_iso(),
        "finished_at": None,
        "decision": None,
        "nodes_visited": [],
        "explainability": dict(EXPLAINABILITY_CONTRACT),
        "steps": [],
    }


def _fact_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Structured facts only — never raw customer text or model CoT."""
    return {
        "amount": state.get("amount")
        if state.get("amount") is not None
        else state.get("claimed_amount"),
        "currency": state.get("currency"),
        "transaction_id": state.get("transaction_id"),
        "merchant_name": state.get("merchant_name"),
        "transaction_date": state.get("transaction_date"),
        "customer_id": state.get("customer_id"),
        "language": state.get("language"),
        "is_fraud": state.get("is_fraud"),
        "fraud_score": state.get("fraud_score"),
        "fraud_score_normalized": state.get("fraud_score_normalized"),
        "priority": state.get("priority"),
        "sla_breached": state.get("sla_breached"),
        "status": state.get("status"),
    }


def _decision_value(state: dict[str, Any]) -> str | None:
    decision = state.get("decision")
    if decision is None:
        return None
    return decision.value if hasattr(decision, "value") else str(decision)


def _understand_step(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    extracted = after.get("extracted")
    gemini_ran = extracted is not None
    reasons: list[str] = []
    roles: list[str] = []

    if gemini_ran:
        roles.append(ROLE_LLM_EXTRACTION)
        reasons.append("gemini_entity_extraction_only")
    elif before.get("transaction_id") or after.get("transaction_id"):
        roles.append(ROLE_SYSTEM)
        reasons.append("extraction_skipped_structured_transaction_id")
    else:
        roles.append(ROLE_SYSTEM)
        reasons.append("extraction_skipped_or_empty_text")

    if after.get("verified_transaction"):
        roles.append(ROLE_TOOL)
        reasons.append("transaction_lookup_matched")
    elif after.get("transaction_lookup_not_found"):
        roles.append(ROLE_TOOL)
        reasons.append("transaction_lookup_not_found")
    elif after.get("transaction_lookup_failed"):
        roles.append(ROLE_TOOL)
        reasons.append("transaction_lookup_failed")
    elif after.get("transaction_id"):
        roles.append(ROLE_TOOL)
        reasons.append("transaction_lookup_attempted")

    return {
        "step_id": f"STEP-UNDERSTAND-{utc_now_iso()}",
        "node": "understand",
        "roles": roles,
        "summary": (
            "Extract stated facts (Gemini when needed) and optionally look up the transaction; "
            "no resolution decision is made here."
        ),
        "inputs": {
            "has_text": bool(before.get("text")),
            "language_hint": before.get("language"),
            "structured_transaction_id": before.get("transaction_id"),
            "gemini_invoked": gemini_ran,
        },
        "outputs": {
            **_fact_snapshot(after),
            "understood": after.get("understood"),
            "verified_transaction_present": bool(after.get("verified_transaction")),
            "extracted_fields": sorted(extracted.keys()) if isinstance(extracted, dict) else [],
        },
        "reasons": reasons,
        "timestamp": utc_now_iso(),
    }


def _decide_step(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    policy = after.get("policy_evaluation") or {}
    ambiguity = after.get("ambiguity") or {}
    reasons = list(policy.get("reasons") or [])

    if after.get("transaction_lookup_not_found"):
        reasons.append("rule:transaction_lookup_not_found→escalate")
    if after.get("transaction_lookup_failed"):
        reasons.append("rule:transaction_lookup_failed→escalate")
    if after.get("transaction_id_unavailable"):
        reasons.append("rule:transaction_id_unavailable→escalate")
    if after.get("verification_evidence_unavailable"):
        reasons.append("rule:verification_evidence_unavailable→escalate")
    if after.get("escalate_reason") and after.get("escalate_reason") not in reasons:
        reasons.append(f"escalate_reason:{after.get('escalate_reason')}")

    kinds = ambiguity.get("kinds") or []
    if kinds:
        reasons.append(f"ambiguity_kinds={kinds}")
    if after.get("abstained"):
        reasons.append(
            f"abstention_mode={((after.get('abstention') or {}).get('abstention_mode'))}"
        )

    decision = _decision_value(after)
    return {
        "step_id": f"STEP-DECIDE-{utc_now_iso()}",
        "node": "decide",
        "roles": [ROLE_BUSINESS_RULES],
        "summary": (
            "Deterministic policy + ambiguity rules choose auto_resolve / clarify / escalate. "
            "No LLM participates in this decision."
        ),
        "inputs": _fact_snapshot(before),
        "outputs": {
            "decision": decision,
            "policy_decision": policy.get("decision"),
            "missing_fields": after.get("open_questions_fields") or [],
            "abstained": bool(after.get("abstained")),
        },
        "reasons": reasons or ["business_rules_evaluated"],
        "timestamp": utc_now_iso(),
    }


def _act_step(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    decision = _decision_value(after) or _decision_value(before)
    reasons: list[str] = [f"action_for_decision={decision}"]
    roles = [ROLE_SYSTEM]
    if decision in ("auto_resolve", "escalate"):
        roles.append(ROLE_TOOL)
        if after.get("fallback_applied") == "create_case_failed_escalate":
            reasons.append("tool:create_dispute_case_failed→escalate_fallback")
        elif after.get("complaint_id"):
            reasons.append("tool:create_dispute_case_succeeded")
    if decision == "clarify":
        reasons.append(
            f"clarification_fields={[q.get('field') for q in (after.get('open_questions') or [])]}"
        )

    return {
        "step_id": f"STEP-ACT-{utc_now_iso()}",
        "node": "act",
        "roles": roles,
        "summary": "Execute the rule-chosen action (create case, ask clarification, prepare escalate).",
        "inputs": {"decision": decision},
        "outputs": {
            "complaint_id": after.get("complaint_id"),
            "actions_count": len(after.get("actions_taken") or []),
            "open_questions_count": len(after.get("open_questions") or []),
            "fallback_applied": after.get("fallback_applied"),
        },
        "reasons": reasons,
        "timestamp": utc_now_iso(),
    }


def _verify_step(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    details = after.get("verification_details") or {}
    reasons: list[str] = []
    if after.get("verified") is True:
        reasons.append("post_action_verification_ok")
    else:
        reasons.append(f"verify_failed:{details.get('error') or after.get('fallback_applied') or 'unverified'}")
    if after.get("fallback_applied"):
        reasons.append(f"fallback={after.get('fallback_applied')}")

    return {
        "step_id": f"STEP-VERIFY-{utc_now_iso()}",
        "node": "verify",
        "roles": [ROLE_TOOL, ROLE_BUSINESS_RULES],
        "summary": "Re-read persisted side-effects; demote decision on failure (never claim success).",
        "inputs": {
            "decision": _decision_value(before),
            "complaint_id": before.get("complaint_id"),
        },
        "outputs": {
            "verified": after.get("verified"),
            "decision": _decision_value(after),
            "verification_details": {
                k: details.get(k)
                for k in ("found", "error", "mismatches", "skipped", "reason", "record_status")
                if k in details
            },
            "fallback_applied": after.get("fallback_applied"),
        },
        "reasons": reasons,
        "timestamp": utc_now_iso(),
    }


def _escalate_step(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    handoff = after.get("handoff") or {}
    return {
        "step_id": f"STEP-ESCALATE-{utc_now_iso()}",
        "node": "escalate",
        "roles": [ROLE_SYSTEM],
        "summary": "Emit structured HumanHandoff from verified facts and rule reasons (no raw transcript).",
        "inputs": {
            "decision": _decision_value(before),
            "escalate_reason": before.get("escalate_reason"),
        },
        "outputs": {
            "handoff_id": handoff.get("handoff_id"),
            "reason": handoff.get("reason"),
            "complaint_id": (handoff.get("case") or {}).get("complaint_id"),
        },
        "reasons": [
            f"escalate_reason:{before.get('escalate_reason') or handoff.get('reason') or 'graph_decision=escalate'}"
        ],
        "timestamp": utc_now_iso(),
    }


def _approval_gate_step(state: dict[str, Any]) -> dict[str, Any]:
    decision = _decision_value(state)
    return {
        "step_id": f"STEP-APPROVAL-{utc_now_iso()}",
        "node": "approval_gate",
        "roles": [ROLE_SYSTEM, ROLE_BUSINESS_RULES],
        "summary": (
            "Pause before act: customer must approve the rule-proposed final action "
            "(auto_resolve/escalate). Not an LLM decision."
        ),
        "inputs": {"decision": decision, "require_approval": True},
        "outputs": {
            "approval_required": True,
            "approval_decision": state.get("approval_decision"),
        },
        "reasons": [f"human_approval_required_before_act:{decision}"],
        "timestamp": utc_now_iso(),
    }


_STEP_BUILDERS = {
    "understand": _understand_step,
    "decide": _decide_step,
    "act": _act_step,
    "verify": _verify_step,
    "escalate": _escalate_step,
}


def record_node_step(
    trace: dict[str, Any],
    node: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Append one auditable step derived from state before/after a node."""
    builder = _STEP_BUILDERS.get(node)
    if builder is None:
        step = {
            "step_id": f"STEP-{node.upper()}-{utc_now_iso()}",
            "node": node,
            "roles": [ROLE_SYSTEM],
            "summary": f"Completed node {node}",
            "inputs": {},
            "outputs": {},
            "reasons": [f"node={node}"],
            "timestamp": utc_now_iso(),
        }
    else:
        step = builder(before, after)

    steps = list(trace.get("steps") or [])
    steps.append(step)
    visited = list(trace.get("nodes_visited") or [])
    if node not in visited:
        visited.append(node)
    return {**trace, "steps": steps, "nodes_visited": visited}


def record_approval_gate(trace: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    steps = list(trace.get("steps") or [])
    steps.append(_approval_gate_step(state))
    return {**trace, "steps": steps}


def finalize_execution_trace(
    trace: dict[str, Any],
    state: dict[str, Any],
    *,
    log: bool = True,
) -> dict[str, Any]:
    """Close the trace, attach final decision, optionally emit structured logs."""
    decision = _decision_value(state)
    finished = {
        **trace,
        "finished_at": utc_now_iso(),
        "decision": decision,
        "nodes_visited": list(state.get("nodes_visited") or trace.get("nodes_visited") or []),
        "outcome": {
            "decision": decision,
            "verified": state.get("verified"),
            "abstained": bool(state.get("abstained")),
            "approval_required": bool(state.get("approval_required")),
            "complaint_id": state.get("complaint_id"),
            "fallback_applied": state.get("fallback_applied"),
            "escalate_reason": state.get("escalate_reason"),
        },
    }
    if log:
        log_execution_trace(finished)
    return finished


def log_execution_trace(trace: dict[str, Any]) -> None:
    """Emit one JSON log line per run + one line per step (no forbidden fields)."""
    header = {
        "event": "dispute_execution_trace",
        "trace_id": trace.get("trace_id"),
        "decision": trace.get("decision"),
        "nodes_visited": trace.get("nodes_visited"),
        "explainability": trace.get("explainability"),
        "outcome": trace.get("outcome"),
        "started_at": trace.get("started_at"),
        "finished_at": trace.get("finished_at"),
        "schema_version": trace.get("schema_version"),
    }
    logger.info(json.dumps(header, ensure_ascii=True, default=str))
    for step in trace.get("steps") or []:
        logger.info(
            json.dumps(
                {"event": "dispute_execution_step", "trace_id": trace.get("trace_id"), **step},
                ensure_ascii=True,
                default=str,
            )
        )


def assert_trace_has_no_forbidden_fields(trace: dict[str, Any]) -> list[str]:
    """Return forbidden keys found anywhere in the trace payload (for tests)."""
    found: list[str] = []

    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_l = str(key).lower()
                here = f"{path}.{key}" if path else str(key)
                if key_l in FORBIDDEN_TRACE_FIELDS or any(
                    bad in key_l for bad in ("chain_of_thought", "raw_transcript")
                ):
                    found.append(here)
                walk(value, here)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                walk(item, f"{path}[{idx}]")

    walk(trace)
    return found
