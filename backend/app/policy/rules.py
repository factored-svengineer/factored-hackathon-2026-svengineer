"""Deterministic business rules for dispute triage.

These thresholds live in code so the LLM cannot invent business policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class PolicyConfig:
    """Configurable thresholds — override via env in production."""

    high_amount_usd: float = 1000.0
    escalate_amount_usd: float = 5000.0
    fraud_score_auto_resolve: float = 0.85
    fraud_score_ambiguous_low: float = 0.40
    fraud_score_ambiguous_high: float = 0.85
    sla_hours_high_priority: int = 4
    sla_hours_default: int = 24


DEFAULT_POLICY = PolicyConfig()


def priority_from_amount(amount: float, cfg: PolicyConfig = DEFAULT_POLICY) -> Priority:
    if amount >= cfg.escalate_amount_usd:
        return Priority.HIGH
    if amount >= cfg.high_amount_usd:
        return Priority.MEDIUM
    return Priority.LOW


def should_auto_resolve(is_fraud: bool, fraud_score: float, cfg: PolicyConfig = DEFAULT_POLICY) -> bool:
    return is_fraud and fraud_score >= cfg.fraud_score_auto_resolve


def is_ambiguous(fraud_score: float, cfg: PolicyConfig = DEFAULT_POLICY) -> bool:
    return cfg.fraud_score_ambiguous_low <= fraud_score < cfg.fraud_score_ambiguous_high


def should_escalate(
    amount: float,
    priority: Priority,
    sla_hours_remaining: float | None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> bool:
    if amount >= cfg.escalate_amount_usd:
        return True
    if priority == Priority.HIGH:
        return True
    if sla_hours_remaining is not None and sla_hours_remaining <= cfg.sla_hours_high_priority:
        return True
    return False
