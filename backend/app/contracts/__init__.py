"""Shared API / inter-service contracts."""

from app.contracts.handoff import (
    SCHEMA_VERSION,
    HumanHandoff,
    build_example_handoff,
    handoff_json_schema,
)

__all__ = [
    "SCHEMA_VERSION",
    "HumanHandoff",
    "build_example_handoff",
    "handoff_json_schema",
]
