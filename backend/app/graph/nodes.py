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
    """Extract entities with Gemini and classify the dispute with local rules."""
    from app.graph.extract import classify_from_text
    from app.graph.google_extractor import extract_entities_with_google

    text = str(state.get("text") or "")
    extracted = (
        extract_entities_with_google(text, language_hint=state.get("language"))
        if text
        else None
    )
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
    customer_id = state.get("customer_id")
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
        from app.graph.verify_ops import safe_get_transaction

        lookup = safe_get_transaction(transaction_id, transaction_date)
        txn = lookup.value if lookup.ok else None
        tool_failures = list(state.get("tool_failures") or [])
        verification_evidence_unavailable = (
            state.get("verification_evidence_unavailable") is True
        )
        if not lookup.ok:
            tool_failures.append(lookup.to_dict())
            verification_evidence_unavailable = True
        if txn:
            is_fraud = txn.get("is_fraud") if is_fraud is None else is_fraud
            fraud_score = txn.get("fraud_score") if fraud_score is None else fraud_score
            amount = amount if amount is not None else txn.get("amount")
            currency = currency or txn.get("currency")
            merchant_name = merchant_name or txn.get("merchant_name")
            customer_id = customer_id or txn.get("customer_id")
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
        # stash for return below
        state = {
            **state,
            "tool_failures": tool_failures,
            "verification_evidence_unavailable": verification_evidence_unavailable,
        }

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
        "customer_id": customer_id,
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
        DEFAULT_POLICY,
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
    verification_evidence_unavailable = state.get("verification_evidence_unavailable") is True
    if verification_evidence_unavailable:
        decision = Decision.ESCALATE
    verified_transaction = state.get("verified_transaction") or {}
    transaction_denied = (
        str(verified_transaction.get("transaction_status") or "").strip().casefold()
        == "denied"
    )
    if transaction_denied and decision != Decision.ESCALATE:
        decision = Decision.CLARIFY
    verified_non_fraud_low_score = (
        verified_transaction.get("verification_source") == "transactions"
        and verified_transaction.get("is_fraud") is False
        and verified_transaction.get("fraud_score") is not None
        and verified_transaction["fraud_score"]
        < DEFAULT_POLICY.fraud_score_ambiguous_low
    )
    if verified_non_fraud_low_score:
        decision = Decision.ESCALATE

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

    escalate_reason = state.get("escalate_reason")
    if verification_evidence_unavailable:
        escalate_reason = "Customer cannot provide transaction verification evidence"
    elif evaluation.decision == PolicyDecision.ESCALATE:
        escalate_reason = "; ".join(evaluation.reasons)
    elif transaction_denied:
        escalate_reason = (
            "Verified transaction was denied; no completed charge is available to refund"
        )
    elif verified_non_fraud_low_score:
        escalate_reason = (
            "Verified transaction has a low fraud signal; human review is required"
        )

    return {
        **state,
        "node": GraphNode.DECIDE,
        "decision": decision,
        "status": "Escalated" if verification_evidence_unavailable else state.get("status"),
        "policy_evaluation": evaluation.to_dict(),
        "fraud_score_normalized": evaluation.fraud_score_normalized,
        "escalate_reason": escalate_reason,
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
    lang = (language or "en").lower()
    prompts = {
        "en": {
            "amount": "What is the exact amount of the charge you are disputing?",
            "transaction_ref": "Can you provide the transaction ID, or the merchant and transaction date?",
            "transaction_id": "What is the ID of the disputed transaction?",
            "merchant": "What is the name of the merchant?",
            "date": "What was the transaction date?",
            "verification_evidence": "Can you provide a transaction record or statement that helps us verify this charge?",
        },
        "es": {
            "amount": "¿Cuál es el monto exacto del cargo que disputa?",
            "transaction_ref": "¿Puede indicar el ID de la transacción o el comercio y la fecha?",
            "transaction_id": "¿Cuál es el ID de la transacción disputada?",
            "merchant": "¿Cuál es el nombre del comercio?",
            "date": "¿Cuál es la fecha de la transacción?",
            "verification_evidence": "¿Puede proporcionar un registro o estado de cuenta que nos ayude a verificar este cargo?",
        },
        "pt": {
            "amount": "Qual é o valor exato da cobrança que você contesta?",
            "transaction_ref": "Pode informar o ID da transação ou o comércio e a data?",
            "transaction_id": "Qual é o ID da transação contestada?",
            "merchant": "Qual é o nome do comércio?",
            "date": "Qual é a data da transação?",
            "verification_evidence": "Pode fornecer um registro da transação ou extrato que nos ajude a verificar essa cobrança?",
        },
    }
    table = prompts.get(lang, prompts["en"])
    return table.get(field, table["transaction_ref"])


def act(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the chosen action (create dispute case, request clarification, etc.)."""
    from app.graph.verify_ops import (
        apply_create_failure_fallback,
        safe_create_dispute_case,
    )

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
        transaction_status = str(
            (state.get("verified_transaction") or {}).get("transaction_status") or ""
        ).strip().casefold()
        transaction_denied = transaction_status == "denied"
        fields = (
            ["verification_evidence"]
            if transaction_denied
            else list(state.get("open_questions_fields") or [])
        )
        if not fields:
            # Facts present but no fraud signal → ask for verification, not invent fields.
            has_identity = state.get("transaction_id") or (
                state.get("merchant_name") and state.get("transaction_date")
            )
            if state.get("amount") is not None and has_identity:
                fields = ["verification_evidence"]
            else:
                fields = ["amount", "transaction_ref"]
        language = state.get("language")
        lang = str(language or "en").lower()
        abstention = state.get("abstention") or state.get("ambiguity") or {}
        for idx, field_name in enumerate(fields, start=1):
            if transaction_denied and field_name == "verification_evidence":
                denied_prompts = {
                    "en": (
                        "The transaction was denied and was not processed, so there "
                        "is no completed charge to refund. If you see a posted charge, "
                        "please provide a statement so we can review it."
                    ),
                    "es": (
                        "La transacción fue denegada y no se procesó, así que no hay "
                        "un cargo completado que reembolsar. Si ves un cargo aplicado, "
                        "comparte un estado de cuenta para revisarlo."
                    ),
                    "pt": (
                        "A transação foi negada e não foi processada, então não há "
                        "uma cobrança concluída para reembolsar. Se houver uma "
                        "cobrança efetivada, envie um extrato para análise."
                    ),
                }
                prompt = denied_prompts.get(lang, denied_prompts["en"])
            else:
                prompt = _question_prompt(field_name, lang)
            clarification_prompts.append(prompt)
            open_questions.append(
                OpenQuestion(
                    question_id=f"Q-{idx:03d}",
                    field=field_name,
                    prompt=prompt,
                    priority=QuestionPriority.REQUIRED,
                    language=lang if lang in ("es", "pt", "en") else "en",
                ).model_dump(mode="json")
            )
        # Prefer bilingual abstention prompt matching customer language.
        if lang == "pt" and abstention.get("customer_prompt_pt"):
            clarification_prompts.insert(0, abstention["customer_prompt_pt"])
        elif lang == "en" and abstention.get("customer_prompt_en"):
            clarification_prompts.insert(0, abstention["customer_prompt_en"])
        elif lang == "es" and abstention.get("customer_prompt_es"):
            clarification_prompts.insert(0, abstention["customer_prompt_es"])
        elif abstention.get("customer_prompt_en"):
            clarification_prompts.insert(0, abstention["customer_prompt_en"])
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

    if decision_value == Decision.ESCALATE and state.get("verification_evidence_unavailable"):
        language = str(state.get("language") or "en").lower()
        open_questions.append(
            OpenQuestion(
                question_id="Q-VERIFY-001",
                field="verification_evidence",
                prompt="Review available account records to verify the disputed transaction.",
                priority=QuestionPriority.REQUIRED,
                language=language if language in ("es", "pt", "en") else "en",
            ).model_dump(mode="json")
        )

    if decision_value in (Decision.AUTO_RESOLVE, Decision.ESCALATE):
        create_result = safe_create_dispute_case(
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
        if not create_result.ok:
            failed_state = {
                **state,
                "actions_taken": actions,
                "open_questions": open_questions,
                "support_evidence": support_evidence,
                "clarification_prompts": clarification_prompts,
            }
            return {
                **apply_create_failure_fallback(failed_state, create_result),
                "node": GraphNode.ACT,
            }

        record = create_result.value
        complaint_id = record["complaint_id"]
        actions.append(
            ActionTaken(
                action_id=f"ACT-CREATE-{now}",
                action_type=ActionType.CREATE_DISPUTE_CASE,
                status=ActionStatus.SUCCEEDED,
                timestamp=now,
                details={
                    "status": record["status"],
                    "decision": decision_value.value,
                    "attempts": create_result.attempts,
                },
                verification_ref=complaint_id,
            ).model_dump(mode="json")
        )
        support_evidence.append(
            SupportEvidence(
                evidence_id="EV-CASE",
                evidence_type=EvidenceType.COMPLAINT_FIELD,
                summary=(
                    f"Case {complaint_id} created with decision {decision_value.value}; "
                    f"amount={record.get('claimed_amount')} {record.get('currency')}."
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
    from app.graph.verify_ops import (
        apply_verify_failure_fallback,
        case_matches_expected,
        verify_case_persisted,
    )

    decision = state.get("decision")
    decision_value = decision.value if isinstance(decision, Decision) else str(decision)
    verification_details: dict[str, Any] = {"decision": decision_value}

    # Create already failed in act — do not claim success; keep escalate fallback.
    if state.get("fallback_applied") == "create_case_failed_escalate":
        return {
            **state,
            "node": GraphNode.VERIFY,
            "verified": False,
            "verification_details": {
                **verification_details,
                "skipped": True,
                "reason": "create_case_already_failed",
            },
        }

    if decision_value in (
        Decision.AUTO_RESOLVE.value,
        Decision.ESCALATE.value,
        "auto_resolve",
        "escalate",
    ):
        complaint_id = state.get("complaint_id")
        result = verify_case_persisted(complaint_id)
        verification_details.update(
            {
                "complaint_id": complaint_id,
                "tool": result.to_dict(),
            }
        )
        if not result.ok:
            verification_details["error"] = result.error
            verification_details["found"] = False
            return {
                **apply_verify_failure_fallback(state, verification_details),
                "node": GraphNode.VERIFY,
            }

        record = result.value
        ok, mismatches = case_matches_expected(record, state)
        verification_details["found"] = True
        verification_details["record_status"] = record.get("status")
        verification_details["mismatches"] = mismatches
        if not ok:
            verification_details["error"] = "case_field_mismatch"
            return {
                **apply_verify_failure_fallback(state, verification_details),
                "node": GraphNode.VERIFY,
            }

        actions = list(state.get("actions_taken") or [])
        actions.append(
            ActionTaken(
                action_id=f"ACT-VERIFY-OK-{utc_now_iso()}",
                action_type=ActionType.OTHER,
                status=ActionStatus.SUCCEEDED,
                timestamp=utc_now_iso(),
                details=verification_details,
                verification_ref=complaint_id,
            ).model_dump(mode="json")
        )
        return {
            **state,
            "node": GraphNode.VERIFY,
            "verified": True,
            "verification_details": verification_details,
            "actions_taken": actions,
        }

    if decision_value in (Decision.CLARIFY.value, "clarify"):
        prompts = state.get("clarification_prompts") or []
        questions = state.get("open_questions") or []
        verified = bool(prompts or questions)
        verification_details["clarification_count"] = len(questions) or len(prompts)
        if not verified:
            return {
                **apply_verify_failure_fallback(state, verification_details),
                "node": GraphNode.VERIFY,
            }
        return {
            **state,
            "node": GraphNode.VERIFY,
            "verified": True,
            "verification_details": verification_details,
        }

    return {
        **state,
        "node": GraphNode.VERIFY,
        "verified": True,
        "verification_details": verification_details,
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
