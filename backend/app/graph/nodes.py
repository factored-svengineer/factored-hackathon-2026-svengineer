"""Explicit state-graph nodes for dispute processing.

Pipeline: understand → decide → act → verify → escalate
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.contracts.handoff import (
    ActionStatus,
    ActionTaken,
    ActionType,
    EvidenceType,
    OpenQuestion,
    QuestionPriority,
    SupportEvidence,
    utc_now_iso,
)


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


def _merge_prefer_existing(state: dict[str, Any], key: str, value: Any) -> Any:
    current = state.get(key)
    if current is not None and current != "":
        return current
    return value


def understand(state: dict[str, Any]) -> dict[str, Any]:
    """Parse natural-language dispute (ES/PT) and extract entities."""
    from app.graph.extract import classify_from_text, extract_entities
    from app.tools.data import get_transaction

    text = str(state.get("text") or "")
    extracted = extract_entities(text) if text else None
    classified = state.get("classified_category")
    if not classified and text:
        classified = classify_from_text(text)

    amount = _merge_prefer_existing(
        state, "amount", extracted.amount if extracted else state.get("claimed_amount")
    )
    if amount is None:
        amount = state.get("claimed_amount")

    currency = _merge_prefer_existing(
        state, "currency", extracted.currency if extracted else None
    )
    transaction_id = _merge_prefer_existing(
        state, "transaction_id", extracted.transaction_id if extracted else None
    )
    merchant_name = _merge_prefer_existing(
        state, "merchant_name", extracted.merchant_name if extracted else None
    )
    transaction_date = _merge_prefer_existing(
        state, "transaction_date", extracted.transaction_date if extracted else None
    )
    language = _merge_prefer_existing(
        state, "language", extracted.language_hint if extracted else None
    )

    is_fraud = state.get("is_fraud")
    fraud_score = state.get("fraud_score")
    verified_transaction = state.get("verified_transaction")

    if transaction_id and (is_fraud is None or fraud_score is None or not verified_transaction):
        txn = get_transaction(transaction_id)
        if txn:
            is_fraud = txn.get("is_fraud") if is_fraud is None else is_fraud
            fraud_score = txn.get("fraud_score") if fraud_score is None else fraud_score
            amount = amount if amount is not None else txn.get("amount")
            currency = currency or txn.get("currency")
            merchant_name = merchant_name or txn.get("merchant_name")
            transaction_date = transaction_date or (
                str(txn.get("transaction_date")) if txn.get("transaction_date") else None
            )
            verified_transaction = {
                "transaction_id": str(txn["transaction_id"]),
                "customer_id": txn.get("customer_id"),
                "amount": float(txn["amount"]) if txn.get("amount") is not None else None,
                "currency": txn.get("currency"),
                "amount_usd": float(txn["amount_usd"])
                if txn.get("amount_usd") is not None
                else None,
                "merchant_name": txn.get("merchant_name"),
                "transaction_date": str(txn["transaction_date"])
                if txn.get("transaction_date")
                else None,
                "transaction_status": txn.get("transaction_status"),
                "is_fraud": bool(txn["is_fraud"]) if txn.get("is_fraud") is not None else None,
                "fraud_score": None,
                "fraud_score_raw": float(txn["fraud_score"])
                if txn.get("fraud_score") is not None
                else None,
                "verified_at": utc_now_iso(),
                "verification_source": "transactions",
            }
            from app.policy.rules import normalize_fraud_score

            if verified_transaction["fraud_score_raw"] is not None:
                verified_transaction["fraud_score"] = normalize_fraud_score(
                    verified_transaction["fraud_score_raw"]
                )
                if fraud_score is None:
                    fraud_score = verified_transaction["fraud_score_raw"]

    understood = bool(text) and (
        amount is not None or transaction_id is not None or merchant_name is not None
    )

    return {
        **state,
        "node": GraphNode.UNDERSTAND,
        "understood": understood,
        "amount": amount,
        "claimed_amount": state.get("claimed_amount", amount),
        "currency": currency,
        "transaction_id": transaction_id,
        "merchant_name": merchant_name,
        "transaction_date": transaction_date,
        "language": language,
        "is_fraud": is_fraud,
        "fraud_score": fraud_score,
        "classified_category": classified,
        "verified_transaction": verified_transaction,
        "extracted": extracted.to_dict() if extracted else None,
    }


def decide(state: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic policies + fraud signals to choose next action."""
    from app.graph.ambiguity import AbstentionMode, assess_ambiguity
    from app.policy.rules import (
        PolicyDecision,
        evaluate_dispute,
        is_ambiguous_fraud_score,
    )

    evaluation = evaluate_dispute(
        amount=state.get("amount")
        if state.get("amount") is not None
        else state.get("claimed_amount"),
        currency=state.get("currency"),
        is_fraud=state.get("is_fraud"),
        fraud_score=state.get("fraud_score"),
        priority=state.get("priority"),
        sla_breached=state.get("sla_breached"),
        sla_hours_remaining=state.get("sla_hours_remaining"),
        status=state.get("status"),
        transaction_id=state.get("transaction_id"),
        merchant_name=state.get("merchant_name"),
        transaction_date=state.get("transaction_date"),
    )
    decision_map = {
        PolicyDecision.AUTO_RESOLVE: Decision.AUTO_RESOLVE,
        PolicyDecision.CLARIFY: Decision.CLARIFY,
        PolicyDecision.ESCALATE: Decision.ESCALATE,
    }
    decision = decision_map[evaluation.decision]

    ambiguity = assess_ambiguity(
        amount=state.get("amount")
        if state.get("amount") is not None
        else state.get("claimed_amount"),
        transaction_id=state.get("transaction_id"),
        merchant_name=state.get("merchant_name"),
        transaction_date=state.get("transaction_date"),
        is_fraud=state.get("is_fraud"),
        fraud_score_normalized=evaluation.fraud_score_normalized,
        classified_category=state.get("classified_category"),
        text=state.get("text"),
        policy_missing_fields=evaluation.missing_fields,
        ambiguous_fraud=is_ambiguous_fraud_score(state.get("fraud_score")),
        language=state.get("language"),
    )

    from app.graph.ambiguity import AmbiguityKind

    blocking_kinds = {
        AmbiguityKind.MISSING_AMOUNT,
        AmbiguityKind.MISSING_TRANSACTION_REF,
        AmbiguityKind.AMBIGUOUS_FRAUD_SCORE,
        AmbiguityKind.LOW_CLASSIFIER_CONFIDENCE,
        AmbiguityKind.CONFLICTING_SIGNALS,
        AmbiguityKind.UNCLEAR_INTENT,
    }
    # Safe default: blocking ambiguity demotes auto_resolve → clarify (never invent).
    if decision == Decision.AUTO_RESOLVE and any(k in blocking_kinds for k in ambiguity.kinds):
        decision = Decision.CLARIFY

    abstention = None
    if decision == Decision.CLARIFY and ambiguity.is_ambiguous:
        abstention = ambiguity.to_dict()
    elif decision == Decision.AUTO_RESOLVE:
        abstention = None

    return {
        **state,
        "node": GraphNode.DECIDE,
        "decision": decision,
        "policy_evaluation": evaluation.to_dict(),
        "fraud_score_normalized": evaluation.fraud_score_normalized,
        "escalate_reason": "; ".join(evaluation.reasons)
        if evaluation.decision == PolicyDecision.ESCALATE
        else state.get("escalate_reason"),
        "open_questions_fields": evaluation.missing_fields or ambiguity.missing_fields,
        "ambiguity": ambiguity.to_dict(),
        "abstention": abstention,
        "abstained": bool(
            abstention
            and abstention.get("abstention_mode")
            in (AbstentionMode.CLARIFY.value, AbstentionMode.ABSTAIN.value)
        ),
    }


def _question_prompt(field: str, language: str | None) -> str:
    lang = (language or "es").lower()
    prompts = {
        "es": {
            "amount": "¿Cuál es el monto exacto del cargo que disputa?",
            "transaction_ref": "¿Puede indicar el ID de la transacción o el comercio y la fecha?",
            "transaction_id": "¿Cuál es el ID de la transacción disputada?",
            "merchant": "¿Cuál es el nombre del comercio?",
            "date": "¿Cuál es la fecha de la transacción?",
        },
        "pt": {
            "amount": "Qual é o valor exato da cobrança que você contesta?",
            "transaction_ref": "Pode informar o ID da transação ou o comércio e a data?",
            "transaction_id": "Qual é o ID da transação contestada?",
            "merchant": "Qual é o nome do comércio?",
            "date": "Qual é a data da transação?",
        },
    }
    table = prompts.get(lang, prompts["es"])
    return table.get(field, table["transaction_ref"])


def act(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the chosen action (create dispute case, request clarification, etc.)."""
    from app.tools.data import create_dispute_case

    decision = state.get("decision", Decision.CLARIFY)
    if isinstance(decision, Decision):
        decision_value = decision
    else:
        decision_value = Decision(str(decision))

    now = utc_now_iso()
    actions: list[dict[str, Any]] = list(state.get("actions_taken") or [])
    open_questions: list[dict[str, Any]] = list(state.get("open_questions") or [])
    support_evidence: list[dict[str, Any]] = list(state.get("support_evidence") or [])
    clarification_prompts: list[str] = []
    complaint_id = state.get("complaint_id")

    category = state.get("classified_category") or {}
    if isinstance(category, dict) and category.get("category"):
        actions.append(
            ActionTaken(
                action_id=f"ACT-CLASSIFY-{now}",
                action_type=ActionType.CLASSIFY_CATEGORY,
                status=ActionStatus.SUCCEEDED,
                timestamp=now,
                details=category,
            ).model_dump(mode="json")
        )

    if state.get("transaction_id") or state.get("verified_transaction"):
        actions.append(
            ActionTaken(
                action_id=f"ACT-LOOKUP-{now}",
                action_type=ActionType.LOOKUP_TRANSACTION,
                status=ActionStatus.SUCCEEDED
                if state.get("verified_transaction")
                else ActionStatus.ATTEMPTED,
                timestamp=now,
                details={"transaction_id": state.get("transaction_id")},
                verification_ref=state.get("transaction_id"),
            ).model_dump(mode="json")
        )

    if decision_value == Decision.CLARIFY:
        fields = list(state.get("open_questions_fields") or ["amount", "transaction_ref"])
        language = state.get("language")
        abstention = state.get("abstention") or state.get("ambiguity") or {}
        for idx, field_name in enumerate(fields, start=1):
            prompt = _question_prompt(field_name, language)
            clarification_prompts.append(prompt)
            open_questions.append(
                OpenQuestion(
                    question_id=f"Q-{idx:03d}",
                    field=field_name,
                    prompt=prompt,
                    priority=QuestionPriority.REQUIRED,
                    language=language if language in ("es", "pt", "en") else "es",
                ).model_dump(mode="json")
            )
        # Prefer bilingual abstention prompt when available
        if language == "pt" and abstention.get("customer_prompt_pt"):
            clarification_prompts.insert(0, abstention["customer_prompt_pt"])
        elif abstention.get("customer_prompt_es"):
            clarification_prompts.insert(0, abstention["customer_prompt_es"])

        actions.append(
            ActionTaken(
                action_id=f"ACT-CLARIFY-{now}",
                action_type=ActionType.REQUEST_CLARIFICATION,
                status=ActionStatus.SUCCEEDED,
                timestamp=now,
                details={
                    "fields": fields,
                    "prompts": clarification_prompts,
                    "abstention_mode": abstention.get("abstention_mode"),
                    "ambiguity_kinds": abstention.get("kinds") or [],
                    "forbidden_inventions": abstention.get("forbidden_inventions") or [],
                },
            ).model_dump(mode="json")
        )

    if decision_value in (Decision.AUTO_RESOLVE, Decision.ESCALATE):
        record = create_dispute_case(
            {
                "customer_id": state.get("customer_id"),
                "case_type": "Claim" if decision_value == Decision.AUTO_RESOLVE else "Complaint",
                "category": category.get("category") if isinstance(category, dict) else None,
                "subcategory": category.get("subcategory") if isinstance(category, dict) else None,
                "claimed_amount": state.get("amount") or state.get("claimed_amount"),
                "currency": state.get("currency"),
                "priority": state.get("priority") or "Medium",
                "status": "Resolved"
                if decision_value == Decision.AUTO_RESOLVE
                else "Escalated",
                "sla_breached": state.get("sla_breached"),
                "transaction_id": state.get("transaction_id"),
                "decision": decision_value.value,
                "text": state.get("text"),
            }
        )
        complaint_id = record["complaint_id"]
        actions.append(
            ActionTaken(
                action_id=f"ACT-CREATE-{now}",
                action_type=ActionType.CREATE_DISPUTE_CASE,
                status=ActionStatus.SUCCEEDED,
                timestamp=now,
                details={"status": record["status"], "decision": decision_value.value},
                verification_ref=complaint_id,
            ).model_dump(mode="json")
        )
        support_evidence.append(
            SupportEvidence(
                evidence_id="EV-CASE",
                evidence_type=EvidenceType.COMPLAINT_FIELD,
                summary=(
                    f"Caso {complaint_id} creado con decisión {decision_value.value}; "
                    f"monto={record.get('claimed_amount')} {record.get('currency')}."
                ),
                source_ref=complaint_id,
                relevance="case_created",
            ).model_dump(mode="json")
        )

    return {
        **state,
        "node": GraphNode.ACT,
        "complaint_id": complaint_id,
        "actions_taken": actions,
        "open_questions": open_questions,
        "support_evidence": support_evidence,
        "clarification_prompts": clarification_prompts,
    }


def verify(state: dict[str, Any]) -> dict[str, Any]:
    """Confirm that side-effects (e.g. dispute case created) actually persisted."""
    from app.tools.data import get_complaint

    decision = state.get("decision")
    decision_value = decision.value if isinstance(decision, Decision) else str(decision)
    verified = True
    verification_details: dict[str, Any] = {"decision": decision_value}

    if decision_value in (Decision.AUTO_RESOLVE.value, Decision.ESCALATE.value, "auto_resolve", "escalate"):
        complaint_id = state.get("complaint_id")
        record = get_complaint(complaint_id) if complaint_id else None
        verified = record is not None
        verification_details["complaint_id"] = complaint_id
        verification_details["found"] = verified
    elif decision_value in (Decision.CLARIFY.value, "clarify"):
        prompts = state.get("clarification_prompts") or []
        questions = state.get("open_questions") or []
        verified = bool(prompts or questions)
        verification_details["clarification_count"] = len(questions) or len(prompts)

    actions = list(state.get("actions_taken") or [])
    if not verified:
        actions.append(
            ActionTaken(
                action_id=f"ACT-VERIFY-FAIL-{utc_now_iso()}",
                action_type=ActionType.OTHER,
                status=ActionStatus.FAILED,
                timestamp=utc_now_iso(),
                details=verification_details,
            ).model_dump(mode="json")
        )

    return {
        **state,
        "node": GraphNode.VERIFY,
        "verified": verified,
        "verification_details": verification_details,
        "actions_taken": actions,
    }


def escalate(state: dict[str, Any]) -> dict[str, Any]:
    """Build structured human handoff — never raw transcript."""
    from app.contracts.handoff import (
        CaseContext,
        ClassifiedCategory,
        HumanHandoff,
        VerifiedTransaction,
        new_handoff_id,
    )
    from app.policy.rules import normalize_fraud_score

    existing = state.get("handoff")
    if isinstance(existing, HumanHandoff):
        handoff = existing
    elif isinstance(existing, dict) and existing.get("schema_version"):
        handoff = HumanHandoff.model_validate(existing)
    else:
        category = state.get("classified_category")
        if isinstance(category, ClassifiedCategory):
            classified = category
        elif isinstance(category, dict) and category.get("category"):
            classified = ClassifiedCategory.model_validate(category)
        else:
            classified = ClassifiedCategory(category="unknown")

        txn = state.get("verified_transaction")
        if isinstance(txn, dict):
            # Ensure fraud_score normalized for contract
            payload = dict(txn)
            if payload.get("fraud_score") is None and payload.get("fraud_score_raw") is not None:
                payload["fraud_score"] = normalize_fraud_score(payload["fraud_score_raw"])
            if payload.get("verified_at") is None:
                payload["verified_at"] = utc_now_iso()
            txn = VerifiedTransaction.model_validate(payload)

        case = state.get("case")
        if isinstance(case, dict):
            case_ctx = CaseContext.model_validate(case)
        else:
            case_ctx = CaseContext(
                complaint_id=state.get("complaint_id"),
                customer_id=state.get("customer_id"),
                language=state.get("language")
                if state.get("language") in ("es", "pt", "en")
                else None,
                priority=str(state.get("priority")) if state.get("priority") else None,
                sla_breached=state.get("sla_breached"),
                claimed_amount=state.get("amount") or state.get("claimed_amount"),
                currency=state.get("currency"),
                status=str(state.get("status")) if state.get("status") else None,
            )

        fraud_norm = state.get("fraud_score_normalized")
        if fraud_norm is None:
            fraud_norm = normalize_fraud_score(state.get("fraud_score"))

        handoff = HumanHandoff(
            handoff_id=new_handoff_id(),
            created_at=utc_now_iso(),
            reason=str(state.get("escalate_reason") or "graph_decision=escalate"),
            case=case_ctx,
            verified_transaction=txn,
            classified_category=classified,
            fraud_score=fraud_norm,
            actions_taken=list(state.get("actions_taken") or []),
            open_questions=list(state.get("open_questions") or []),
            support_evidence=list(state.get("support_evidence") or []),
        )

    return {
        **state,
        "node": GraphNode.ESCALATE,
        "handoff": handoff.model_dump(mode="json"),
    }
