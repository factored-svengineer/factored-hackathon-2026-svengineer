"""Sequential runner for the explicit dispute state graph."""

from __future__ import annotations

from typing import Any

from app.graph.nodes import (
    Decision,
    GraphNode,
    act,
    decide,
    escalate,
    understand,
    verify,
)


def run_dispute_graph(initial_state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute understand → decide → act → verify → (escalate if needed)."""
    state: dict[str, Any] = dict(initial_state or {})
    visited: list[str] = []

    state = understand(state)
    visited.append(GraphNode.UNDERSTAND.value)

    state = decide(state)
    visited.append(GraphNode.DECIDE.value)

    decision = state.get("decision", Decision.CLARIFY)
    decision_value = decision.value if isinstance(decision, Decision) else str(decision)
    approval_granted = (
        state.get("approval_granted") is True
        and state.get("approval_decision") == decision_value
    )
    if state.get("require_approval") is True and decision_value in (
        Decision.AUTO_RESOLVE.value,
        Decision.ESCALATE.value,
    ) and not approval_granted:
        state["approval_required"] = True
        state["approval_decision"] = decision_value
        state["nodes_visited"] = visited
        state["decision"] = decision_value
        return state

    state["approval_required"] = False
    state = act(state)
    visited.append(GraphNode.ACT.value)

    state = verify(state)
    visited.append(GraphNode.VERIFY.value)

    decision = state.get("decision", Decision.CLARIFY)
    if decision == Decision.ESCALATE or decision == Decision.ESCALATE.value:
        state = escalate(state)
        visited.append(GraphNode.ESCALATE.value)

    state["nodes_visited"] = visited
    state["decision"] = decision.value if isinstance(decision, Decision) else str(decision)
    return state
