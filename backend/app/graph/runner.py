"""Sequential runner for the explicit dispute state graph (stubs)."""

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
    """Execute understand → decide → act → verify → (escalate if needed).

    Nodes are stubs today; this runner exists so FastAPI / Docker can exercise
    the full pipeline wiring before Sprint 2 implementations land.
    """
    state: dict[str, Any] = dict(initial_state or {})
    visited: list[str] = []

    state = understand(state)
    visited.append(GraphNode.UNDERSTAND.value)

    state = decide(state)
    visited.append(GraphNode.DECIDE.value)

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
