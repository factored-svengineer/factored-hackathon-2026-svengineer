"""Explicit ambiguity detection and abstention (Issue #9).

When monto/fecha/comercio (or fraud signal) are missing/unclear, the system
must CLARIFY or ABSTAIN — never invent facts for auto_resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AmbiguityKind(str, Enum):
    MISSING_AMOUNT = "missing_amount"
    MISSING_DATE = "missing_date"
    MISSING_MERCHANT = "missing_merchant"
    MISSING_TRANSACTION_REF = "missing_transaction_ref"
    AMBIGUOUS_FRAUD_SCORE = "ambiguous_fraud_score"
    LOW_CLASSIFIER_CONFIDENCE = "low_classifier_confidence"
    CONFLICTING_SIGNALS = "conflicting_signals"
    UNCLEAR_INTENT = "unclear_intent"


class AbstentionMode(str, Enum):
    """clarify = ask the customer; abstain = refuse to auto-resolve without guessing."""

    CLARIFY = "clarify"
    ABSTAIN = "abstain"


# Fields the model / graph must never fabricate to force a resolution.
FORBIDDEN_INVENTIONS = (
    "amount",
    "currency",
    "transaction_date",
    "merchant_name",
    "transaction_id",
    "is_fraud",
    "fraud_score",
)

_MESSAGES = {
    AmbiguityKind.MISSING_AMOUNT: {
        "es": "Falta el monto de la transacción disputada.",
        "pt": "Falta o valor da transação contestada.",
    },
    AmbiguityKind.MISSING_DATE: {
        "es": "Falta la fecha de la transacción.",
        "pt": "Falta a data da transação.",
    },
    AmbiguityKind.MISSING_MERCHANT: {
        "es": "Falta el comercio o beneficiario del cargo.",
        "pt": "Falta o comércio ou beneficiário da cobrança.",
    },
    AmbiguityKind.MISSING_TRANSACTION_REF: {
        "es": "No hay ID de transacción ni comercio+fecha suficientes para localizar el movimiento.",
        "pt": "Não há ID de transação nem comércio+data suficientes para localizar o movimento.",
    },
    AmbiguityKind.AMBIGUOUS_FRAUD_SCORE: {
        "es": "La señal de fraude es ambigua; no se puede resolver automáticamente.",
        "pt": "O sinal de fraude é ambíguo; não é possível resolver automaticamente.",
    },
    AmbiguityKind.LOW_CLASSIFIER_CONFIDENCE: {
        "es": "La categoría de la disputa no es clara (confianza baja).",
        "pt": "A categoria da disputa não está clara (confiança baixa).",
    },
    AmbiguityKind.CONFLICTING_SIGNALS: {
        "es": "Hay señales contradictorias (p. ej. is_fraud vs. score).",
        "pt": "Há sinais contraditórios (ex.: is_fraud vs. score).",
    },
    AmbiguityKind.UNCLEAR_INTENT: {
        "es": "No está claro qué disputa el cliente; se necesita clarificación.",
        "pt": "Não está claro o que o cliente contesta; é necessária clarificação.",
    },
}


@dataclass(frozen=True)
class AmbiguityAssessment:
    is_ambiguous: bool
    kinds: list[AmbiguityKind] = field(default_factory=list)
    abstention_mode: AbstentionMode | None = None
    missing_fields: list[str] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)
    forbidden_inventions: tuple[str, ...] = FORBIDDEN_INVENTIONS
    customer_prompt_es: str | None = None
    customer_prompt_pt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_ambiguous": self.is_ambiguous,
            "kinds": [k.value for k in self.kinds],
            "abstention_mode": self.abstention_mode.value if self.abstention_mode else None,
            "missing_fields": list(self.missing_fields),
            "messages": list(self.messages),
            "forbidden_inventions": list(self.forbidden_inventions),
            "customer_prompt_es": self.customer_prompt_es,
            "customer_prompt_pt": self.customer_prompt_pt,
        }


def _classifier_confidence(classified: Any) -> float | None:
    if isinstance(classified, dict):
        value = classified.get("confidence")
        return float(value) if value is not None else None
    return None


def assess_ambiguity(
    *,
    amount: float | None = None,
    transaction_id: str | None = None,
    merchant_name: str | None = None,
    transaction_date: str | None = None,
    is_fraud: bool | None = None,
    fraud_score_normalized: float | None = None,
    classified_category: Any = None,
    text: str | None = None,
    policy_missing_fields: list[str] | None = None,
    ambiguous_fraud: bool = False,
    language: str | None = None,
) -> AmbiguityAssessment:
    """Return structured ambiguity assessment. Never suggests inventing fields."""
    kinds: list[AmbiguityKind] = []
    missing: list[str] = []

    if amount is None:
        kinds.append(AmbiguityKind.MISSING_AMOUNT)
        missing.append("amount")
    if not transaction_date:
        kinds.append(AmbiguityKind.MISSING_DATE)
        missing.append("date")
    if not merchant_name:
        kinds.append(AmbiguityKind.MISSING_MERCHANT)
        missing.append("merchant")
    if not transaction_id and not (merchant_name and transaction_date):
        kinds.append(AmbiguityKind.MISSING_TRANSACTION_REF)
        missing.append("transaction_ref")

    # Align with policy-required subset when provided
    if policy_missing_fields:
        for field_name in policy_missing_fields:
            if field_name not in missing:
                missing.append(field_name)

    if ambiguous_fraud:
        kinds.append(AmbiguityKind.AMBIGUOUS_FRAUD_SCORE)

    confidence = _classifier_confidence(classified_category)
    if confidence is not None and confidence < 0.5:
        kinds.append(AmbiguityKind.LOW_CLASSIFIER_CONFIDENCE)

    if is_fraud is False and fraud_score_normalized is not None and fraud_score_normalized >= 0.85:
        kinds.append(AmbiguityKind.CONFLICTING_SIGNALS)
    if is_fraud is True and fraud_score_normalized is not None and fraud_score_normalized < 0.40:
        kinds.append(AmbiguityKind.CONFLICTING_SIGNALS)

    vague = (
        "algo raro",
        "não sei",
        "no se",
        "no sé",
        "tal vez",
        "talvez",
        "creo que",
        "acho que",
    )
    if text and any(token in text.lower() for token in vague) and amount is None:
        kinds.append(AmbiguityKind.UNCLEAR_INTENT)

    # Dedupe kinds preserving order
    seen: set[AmbiguityKind] = set()
    ordered: list[AmbiguityKind] = []
    for kind in kinds:
        if kind not in seen:
            seen.add(kind)
            ordered.append(kind)

    is_ambiguous = bool(ordered)
    if not is_ambiguous:
        return AmbiguityAssessment(is_ambiguous=False)

    messages = [
        {"kind": kind.value, "es": _MESSAGES[kind]["es"], "pt": _MESSAGES[kind]["pt"]}
        for kind in ordered
    ]

    # Abstain (refuse auto-resolve) whenever ambiguous; clarify when we can ask for facts.
    askable = {
        AmbiguityKind.MISSING_AMOUNT,
        AmbiguityKind.MISSING_DATE,
        AmbiguityKind.MISSING_MERCHANT,
        AmbiguityKind.MISSING_TRANSACTION_REF,
        AmbiguityKind.UNCLEAR_INTENT,
    }
    mode = (
        AbstentionMode.CLARIFY
        if any(k in askable for k in ordered)
        else AbstentionMode.ABSTAIN
    )

    prompt_es = "Para continuar sin inventar datos, necesitamos: " + "; ".join(
        _MESSAGES[k]["es"] for k in ordered if k in askable
    )
    prompt_pt = "Para continuar sem inventar dados, precisamos: " + "; ".join(
        _MESSAGES[k]["pt"] for k in ordered if k in askable
    )
    if mode == AbstentionMode.ABSTAIN and not any(k in askable for k in ordered):
        prompt_es = "El caso es ambiguo; nos abstenemos de resolver automáticamente."
        prompt_pt = "O caso é ambíguo; nos abstemos de resolver automaticamente."

    return AmbiguityAssessment(
        is_ambiguous=True,
        kinds=ordered,
        abstention_mode=mode,
        missing_fields=missing,
        messages=messages,
        customer_prompt_es=prompt_es,
        customer_prompt_pt=prompt_pt,
    )


def assert_no_invented_fields(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    allowed_from_lookup: bool = False,
) -> list[str]:
    """Return forbidden fields that appeared from null→value without a lookup source.

    Used in tests / verify guards. When ``allowed_from_lookup`` is True (txn
    verified from data store), filling fraud fields is permitted.
    """
    violations: list[str] = []
    for key in FORBIDDEN_INVENTIONS:
        if allowed_from_lookup and key in {"is_fraud", "fraud_score", "amount", "currency", "merchant_name", "transaction_date"}:
            continue
        was_missing = before.get(key) in (None, "")
        now_set = after.get(key) not in (None, "")
        invented = after.get("_invented_fields") or []
        if was_missing and now_set and key in invented:
            violations.append(key)
    return violations
