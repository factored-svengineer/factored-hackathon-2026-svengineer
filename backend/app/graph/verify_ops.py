"""Post-action verification and safe fallbacks for tool failures (Issue #13)."""

from __future__ import annotations

from typing import Any

from app.contracts.handoff import ActionStatus, ActionTaken, ActionType, utc_now_iso
from app.tools.resilience import ToolFailureKind, ToolResult, call_tool

AUTO_RESOLVE = "auto_resolve"
ESCALATE = "escalate"
CLARIFY = "clarify"


def _decision_value(state: dict[str, Any]) -> str:
    decision = state.get("decision", CLARIFY)
    return decision.value if hasattr(decision, "value") else str(decision)


def verify_case_persisted(complaint_id: str | None) -> ToolResult:
    """Re-read the dispute case from the system of record."""
    from app.tools.data import get_complaint

    if not complaint_id:
        return ToolResult(
            ok=False,
            error="complaint_id_missing",
            failure_kind=ToolFailureKind.NOT_FOUND,
            tool_name="get_complaint",
            attempts=0,
        )

    result = call_tool("get_complaint", get_complaint, complaint_id, retries=1)
    if not result.ok:
        return result
    if result.value is None:
        return ToolResult(
            ok=False,
            error="case_not_found_after_create",
            failure_kind=ToolFailureKind.NOT_FOUND,
            attempts=result.attempts,
            tool_name="get_complaint",
            details={"complaint_id": complaint_id},
        )
    return result


def case_matches_expected(record: dict[str, Any], state: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check persisted case reflects the intended decision/status."""
    mismatches: list[str] = []
    expected_decision = _decision_value(state)
    # After fallback, expected_decision may already be escalate
    recorded_decision = record.get("decision")
    if recorded_decision and recorded_decision != expected_decision:
        # Allow auto_resolve→escalate demotion records when fallback rewrote decision
        if not (
            recorded_decision == AUTO_RESOLVE
            and expected_decision == ESCALATE
        ):
            mismatches.append(
                f"decision_mismatch recorded={recorded_decision} expected={expected_decision}"
            )

    expected_status = {
        AUTO_RESOLVE: "Resolved",
        ESCALATE: "Escalated",
    }.get(expected_decision)
    if expected_status and record.get("status") and record.get("status") != expected_status:
        # If we demoted auto_resolve after a failed verify, status may still be Resolved
        if not (
            record.get("status") == "Resolved"
            and expected_decision == ESCALATE
        ):
            mismatches.append(
                f"status_mismatch recorded={record.get('status')} expected={expected_status}"
            )

    if state.get("customer_id") and record.get("customer_id") not in (
        None,
        state.get("customer_id"),
    ):
        mismatches.append("customer_id_mismatch")

    return (not mismatches, mismatches)


def safe_create_dispute_case(payload: dict[str, Any]) -> ToolResult:
    """Create a dispute case with retry; surface failures instead of crashing the graph."""
    from app.tools.data import create_dispute_case

    return call_tool("create_dispute_case", create_dispute_case, payload, retries=1)


def safe_get_transaction(
    transaction_id: str, transaction_date: str | None = None
) -> ToolResult:
    """Lookup transaction; config/lookup errors become soft failures."""
    from app.tools.data import get_transaction

    return call_tool(
        "get_transaction",
        get_transaction,
        transaction_id,
        transaction_date,
        retries=0,
    )


def apply_create_failure_fallback(
    state: dict[str, Any],
    tool_result: ToolResult,
) -> dict[str, Any]:
    """When case creation fails: never claim success; demote to escalate + clarify ask."""
    now = utc_now_iso()
    actions = list(state.get("actions_taken") or [])
    actions.append(
        ActionTaken(
            action_id=f"ACT-CREATE-FAIL-{now}",
            action_type=ActionType.CREATE_DISPUTE_CASE,
            status=ActionStatus.FAILED,
            timestamp=now,
            details=tool_result.to_dict(),
        ).model_dump(mode="json")
    )
    language = str(state.get("language") or "es").lower()
    prompts = {
        "es": "No pudimos registrar el caso automáticamente. Un agente lo revisará.",
        "pt": "Não foi possível registrar o caso automaticamente. Um agente irá revisar.",
        "en": "We could not register the case automatically. A human agent will review it.",
    }
    prompt = prompts.get(language, prompts["en"])
    open_questions = list(state.get("open_questions") or [])
    open_questions.append(
        {
            "question_id": "Q-TOOL-FALLBACK-001",
            "field": "case_registration",
            "prompt": prompt,
            "priority": "required",
            "language": language if language in ("es", "pt", "en") else "en",
        }
    )
    return {
        **state,
        "decision": ESCALATE,
        "complaint_id": None,
        "verified": False,
        "tool_failures": list(state.get("tool_failures") or []) + [tool_result.to_dict()],
        "fallback_applied": "create_case_failed_escalate",
        "escalate_reason": (
            f"tool_failure:create_dispute_case:{tool_result.failure_kind.value}"
            if tool_result.failure_kind
            else "tool_failure:create_dispute_case"
        ),
        "actions_taken": actions,
        "open_questions": open_questions,
        "clarification_prompts": list(state.get("clarification_prompts") or []) + [prompt],
    }


def apply_verify_failure_fallback(
    state: dict[str, Any],
    verification_details: dict[str, Any],
) -> dict[str, Any]:
    """When post-action verify fails: do not report success; escalate safely."""
    now = utc_now_iso()
    actions = list(state.get("actions_taken") or [])
    actions.append(
        ActionTaken(
            action_id=f"ACT-VERIFY-FAIL-{now}",
            action_type=ActionType.OTHER,
            status=ActionStatus.FAILED,
            timestamp=now,
            details=verification_details,
        ).model_dump(mode="json")
    )
    decision = _decision_value(state)
    next_decision = decision
    fallback = "verify_failed_mark_unverified"
    if decision == AUTO_RESOLVE:
        next_decision = ESCALATE
        fallback = "verify_failed_demote_auto_resolve_to_escalate"

    return {
        **state,
        "decision": next_decision,
        "verified": False,
        "verification_details": verification_details,
        "actions_taken": actions,
        "fallback_applied": fallback,
        "escalate_reason": state.get("escalate_reason")
        or f"verify_failed:{verification_details.get('error', 'case_not_confirmed')}",
        "tool_failures": list(state.get("tool_failures") or [])
        + [{"tool_name": "verify", "details": verification_details}],
    }
