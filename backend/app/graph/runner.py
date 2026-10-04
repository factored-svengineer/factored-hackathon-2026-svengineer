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
from app.graph.tracing import (
    finalize_execution_trace,
    record_approval_gate,
    record_node_step,
    start_execution_trace,
)


def run_dispute_graph(initial_state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute understand → decide → act → verify → (escalate if needed).

    Builds an auditable ``execution_trace`` (Issue #14): facts + business-rule
    reasons. Gemini extraction never appears as the decision authority.
    """
    state: dict[str, Any] = dict(initial_state or {})
    visited: list[str] = []
    trace = start_execution_trace(state)

    before = dict(state)
    state = understand(state)
    visited.append(GraphNode.UNDERSTAND.value)
    trace = record_node_step(trace, GraphNode.UNDERSTAND.value, before, state)

    before = dict(state)
    state = decide(state)
    visited.append(GraphNode.DECIDE.value)
    trace = record_node_step(trace, GraphNode.DECIDE.value, before, state)

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
        trace = record_approval_gate(trace, state)
        state["execution_trace"] = finalize_execution_trace(trace, state)
        state["trace_id"] = state["execution_trace"]["trace_id"]
        return state

    state["approval_required"] = False

    before = dict(state)
    state = act(state)
    visited.append(GraphNode.ACT.value)
    trace = record_node_step(trace, GraphNode.ACT.value, before, state)

    before = dict(state)
    state = verify(state)
    visited.append(GraphNode.VERIFY.value)
    trace = record_node_step(trace, GraphNode.VERIFY.value, before, state)

    decision = state.get("decision", Decision.CLARIFY)
    if decision == Decision.ESCALATE or decision == Decision.ESCALATE.value:
        before = dict(state)
        state = escalate(state)
        visited.append(GraphNode.ESCALATE.value)
        trace = record_node_step(trace, GraphNode.ESCALATE.value, before, state)

    state["nodes_visited"] = visited
    state["decision"] = decision.value if isinstance(decision, Decision) else str(decision)
    state["execution_trace"] = finalize_execution_trace(trace, state)
    state["trace_id"] = state["execution_trace"]["trace_id"]
    return state
