"""Deterministic business rules for dispute triage.

These thresholds live in code so the LLM cannot invent business policy.
The graph `decide` node must call this layer — never ask the model for
amount / priority / SLA thresholds.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecision(str, Enum):
    AUTO_RESOLVE = "auto_resolve"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class PolicyConfig:
    """Configurable thresholds — override via env in production."""

    high_amount_usd: float = 1000.0
    escalate_amount_usd: float = 5000.0
    fraud_score_auto_resolve: float = 0.85
    fraud_score_ambiguous_low: float = 0.40
    fraud_score_ambiguous_high: float = 0.85
    # Dataset scores are often 0–100; values above this are treated as raw and /100.
    fraud_score_raw_threshold: float = 1.0
    sla_hours_high_priority: int = 4
    sla_hours_default: int = 24
    # Missing any of these blocks auto_resolve and favors clarify (unless escalate wins).
    required_fields_for_resolve: tuple[str, ...] = ("amount", "transaction_ref")


def load_policy_config() -> PolicyConfig:
    """Build config from defaults + optional environment overrides."""

    def _f(name: str, default: float) -> float:
        raw = os.getenv(name)
        return float(raw) if raw not in (None, "") else default

    def _i(name: str, default: int) -> int:
        raw = os.getenv(name)
        return int(raw) if raw not in (None, "") else default

    return PolicyConfig(
        high_amount_usd=_f("POLICY_HIGH_AMOUNT_USD", 1000.0),
        escalate_amount_usd=_f("POLICY_ESCALATE_AMOUNT_USD", 5000.0),
        fraud_score_auto_resolve=_f("POLICY_FRAUD_AUTO_RESOLVE", 0.85),
        fraud_score_ambiguous_low=_f("POLICY_FRAUD_AMBIGUOUS_LOW", 0.40),
        fraud_score_ambiguous_high=_f("POLICY_FRAUD_AMBIGUOUS_HIGH", 0.85),
        fraud_score_raw_threshold=_f("POLICY_FRAUD_RAW_THRESHOLD", 1.0),
        sla_hours_high_priority=_i("POLICY_SLA_HOURS_HIGH_PRIORITY", 4),
        sla_hours_default=_i("POLICY_SLA_HOURS_DEFAULT", 24),
    )


DEFAULT_POLICY = load_policy_config()


def normalize_fraud_score(
    score: float | None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> float | None:
    """Return fraud score in [0, 1].

    Datathon `transactions.fraud_score` is typically 0–100. Values already in
    [0, 1] are left as-is. ``None`` stays ``None``.
    """
    if score is None:
        return None
    value = float(score)
    if value < 0:
        return 0.0
    if value > cfg.fraud_score_raw_threshold:
        value = value / 100.0
    return min(1.0, value)


def parse_priority(value: str | Priority | None) -> Priority | None:
    if value is None:
        return None
    if isinstance(value, Priority):
        return value
    normalized = str(value).strip().lower()
    mapping = {
        "low": Priority.LOW,
        "medium": Priority.MEDIUM,
        "med": Priority.MEDIUM,
        "high": Priority.HIGH,
        "critical": Priority.CRITICAL,
        "critica": Priority.CRITICAL,
        "crítica": Priority.CRITICAL,
    }
    return mapping.get(normalized)


def priority_from_amount(amount: float, cfg: PolicyConfig = DEFAULT_POLICY) -> Priority:
    if amount >= cfg.escalate_amount_usd:
        return Priority.HIGH
    if amount >= cfg.high_amount_usd:
        return Priority.MEDIUM
    return Priority.LOW


def effective_priority(
    amount: float | None,
    declared_priority: str | Priority | None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> Priority:
    """Take the max of amount-derived and complaint-declared priority."""
    declared = parse_priority(declared_priority) or Priority.LOW
    from_amount = priority_from_amount(amount or 0.0, cfg)
    order = [Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.CRITICAL]
    return order[max(order.index(declared), order.index(from_amount))]


def should_auto_resolve(
    is_fraud: bool | None,
    fraud_score: float | None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> bool:
    normalized = normalize_fraud_score(fraud_score, cfg)
    if not is_fraud or normalized is None:
        return False
    return normalized >= cfg.fraud_score_auto_resolve


def is_ambiguous_fraud_score(
    fraud_score: float | None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> bool:
    normalized = normalize_fraud_score(fraud_score, cfg)
    if normalized is None:
        return False
    return cfg.fraud_score_ambiguous_low <= normalized < cfg.fraud_score_ambiguous_high


def should_escalate(
    *,
    amount: float | None = None,
    priority: str | Priority | None = None,
    sla_hours_remaining: float | None = None,
    sla_breached: bool | None = None,
    status: str | None = None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> bool:
    eff = effective_priority(amount, priority, cfg)
    if amount is not None and amount >= cfg.escalate_amount_usd:
        return True
    if eff in (Priority.HIGH, Priority.CRITICAL):
        return True
    if sla_breached is True:
        return True
    if status and str(status).strip().lower() == "escalated":
        return True
    return (
        sla_hours_remaining is not None
        and sla_hours_remaining <= cfg.sla_hours_high_priority
    )


def missing_required_fields(
    *,
    amount: float | None,
    transaction_id: str | None,
    merchant_name: str | None = None,
    transaction_date: str | None = None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> list[str]:
    """Fields the system still needs before a safe auto-resolve."""
    missing: list[str] = []
    checks = {
        "amount": amount is not None,
        "transaction_ref": bool(transaction_id) or bool(merchant_name and transaction_date),
        "transaction_id": bool(transaction_id),
        "merchant": bool(merchant_name),
        "date": bool(transaction_date),
    }
    for name in cfg.required_fields_for_resolve:
        if name in checks and not checks[name]:
            missing.append(name)
    return missing


@dataclass(frozen=True)
class PolicyEvaluation:
    """Explainable output of the deterministic policy layer."""

    decision: PolicyDecision
    reasons: list[str] = field(default_factory=list)
    priority: Priority = Priority.LOW
    fraud_score_normalized: float | None = None
    missing_fields: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        payload["priority"] = self.priority.value
        return payload


def evaluate_dispute(
    *,
    amount: float | None = None,
    currency: str | None = None,
    is_fraud: bool | None = None,
    fraud_score: float | None = None,
    priority: str | Priority | None = None,
    sla_breached: bool | None = None,
    sla_hours_remaining: float | None = None,
    status: str | None = None,
    transaction_id: str | None = None,
    merchant_name: str | None = None,
    transaction_date: str | None = None,
    cfg: PolicyConfig = DEFAULT_POLICY,
) -> PolicyEvaluation:
    """Decide auto_resolve | clarify | escalate using code-only rules.

    Precedence (safe by default):
    1. Escalate if SLA/priority/amount/status demand a human
    2. Clarify if required facts are missing or fraud score is ambiguous
    3. Auto-resolve only when fraud is clear AND facts are sufficient AND
       no escalate signal fired
    """
    normalized = normalize_fraud_score(fraud_score, cfg)
    eff_priority = effective_priority(amount, priority, cfg)
    missing = missing_required_fields(
        amount=amount,
        transaction_id=transaction_id,
        merchant_name=merchant_name,
        transaction_date=transaction_date,
        cfg=cfg,
    )
    reasons: list[str] = []
    signals: dict[str, Any] = {
        "amount": amount,
        "currency": currency,
        "is_fraud": is_fraud,
        "fraud_score_raw": fraud_score,
        "fraud_score_normalized": normalized,
        "declared_priority": str(priority) if priority is not None else None,
        "effective_priority": eff_priority.value,
        "sla_breached": sla_breached,
        "sla_hours_remaining": sla_hours_remaining,
        "status": status,
        "transaction_id": transaction_id,
    }

    escalate = should_escalate(
        amount=amount,
        priority=priority,
        sla_hours_remaining=sla_hours_remaining,
        sla_breached=sla_breached,
        status=status,
        cfg=cfg,
    )
    if escalate:
        if amount is not None and amount >= cfg.escalate_amount_usd:
            reasons.append(f"amount>={cfg.escalate_amount_usd}")
        if eff_priority in (Priority.HIGH, Priority.CRITICAL):
            reasons.append(f"priority={eff_priority.value}")
        if sla_breached is True:
            reasons.append("sla_breached=true")
        if status and str(status).strip().lower() == "escalated":
            reasons.append("status=Escalated")
        if (
            sla_hours_remaining is not None
            and sla_hours_remaining <= cfg.sla_hours_high_priority
        ):
            reasons.append(f"sla_hours_remaining<={cfg.sla_hours_high_priority}")
        return PolicyEvaluation(
            decision=PolicyDecision.ESCALATE,
            reasons=reasons or ["escalate_signal"],
            priority=eff_priority,
            fraud_score_normalized=normalized,
            missing_fields=missing,
            signals=signals,
        )

    if missing:
        reasons.append(f"missing_fields={missing}")
        return PolicyEvaluation(
            decision=PolicyDecision.CLARIFY,
            reasons=reasons,
            priority=eff_priority,
            fraud_score_normalized=normalized,
            missing_fields=missing,
            signals=signals,
        )

    if is_ambiguous_fraud_score(fraud_score, cfg) and not is_fraud:
        reasons.append(
            f"fraud_score_ambiguous in "
            f"[{cfg.fraud_score_ambiguous_low},{cfg.fraud_score_ambiguous_high})"
        )
        return PolicyEvaluation(
            decision=PolicyDecision.CLARIFY,
            reasons=reasons,
            priority=eff_priority,
            fraud_score_normalized=normalized,
            missing_fields=missing,
            signals=signals,
        )

    if should_auto_resolve(is_fraud, fraud_score, cfg):
        reasons.append(
            f"is_fraud=true and fraud_score_normalized>={cfg.fraud_score_auto_resolve}"
        )
        return PolicyEvaluation(
            decision=PolicyDecision.AUTO_RESOLVE,
            reasons=reasons,
            priority=eff_priority,
            fraud_score_normalized=normalized,
            missing_fields=missing,
            signals=signals,
        )

    reasons.append("no_clear_fraud_or_escalate_signal")
    return PolicyEvaluation(
        decision=PolicyDecision.CLARIFY,
        reasons=reasons,
        priority=eff_priority,
        fraud_score_normalized=normalized,
        missing_fields=missing,
        signals=signals,
    )


# Backwards-compatible alias used by early stubs / docs.
def is_ambiguous(fraud_score: float, cfg: PolicyConfig = DEFAULT_POLICY) -> bool:
    return is_ambiguous_fraud_score(fraud_score, cfg)
