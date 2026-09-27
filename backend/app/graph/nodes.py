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
    # TODO: assemble verified facts, actions, evidence, open questions
    return {
        **state,
        "node": GraphNode.ESCALATE,
        "handoff": {
            "verified_transaction": None,
            "classified_category": None,
            "fraud_score": None,
            "actions_taken": [],
            "open_questions": [],
            "support_evidence": [],
        },
    }
