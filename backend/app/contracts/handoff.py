"""Human handoff JSON contract (v1).

Shared by backend graph, frontend, and data-pipeline.
NEVER include raw call transcripts — only verified facts and short summaries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0.0"


class ActionType(str, Enum):
    CREATE_DISPUTE_CASE = "create_dispute_case"
    REQUEST_CLARIFICATION = "request_clarification"
    APPLY_COMPENSATION = "apply_compensation"
    LOOKUP_TRANSACTION = "lookup_transaction"
    CLASSIFY_CATEGORY = "classify_category"
    CHECK_FRAUD = "check_fraud"
    OTHER = "other"


class ActionStatus(str, Enum):
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvidenceType(str, Enum):
    POLICY_EXCERPT = "policy_excerpt"
    TRANSCRIPT_SUMMARY = "transcript_summary"
    COMPLAINT_FIELD = "complaint_field"
    TRANSACTION_FIELD = "transaction_field"
    CUSTOMER_PROFILE = "customer_profile"
    OTHER = "other"


class QuestionPriority(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class VerifiedTransaction(BaseModel):
    """Transaction facts confirmed against the source of truth (e.g. DuckDB/S3)."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    customer_id: str | None = None
    amount: float | None = None
    currency: str | None = None
    amount_usd: float | None = None
    merchant_name: str | None = None
    transaction_date: str | None = Field(
        default=None, description="ISO-8601 timestamp when known"
    )
    transaction_status: str | None = None
    is_fraud: bool | None = None
    fraud_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalized fraud score in [0, 1]. Divide raw dataset scores by 100.",
    )
    fraud_score_raw: float | None = Field(
        default=None,
        description="Original score from source data when scale differs (e.g. 0–100).",
    )
    verified_at: str = Field(description="ISO-8601 UTC timestamp of verification")
    verification_source: str = Field(
        default="transactions",
        description="Table/system used to verify the transaction",
    )


class ClassifiedCategory(BaseModel):
    """Dispute category/subcategory from classifier or rules."""

    model_config = ConfigDict(extra="forbid")

    category: str
    subcategory: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    classifier: Literal["baseline", "proposed", "rules", "human"] | None = None


class ActionTaken(BaseModel):
    """Side-effect attempted or confirmed during act/verify."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: ActionType
    status: ActionStatus
    timestamp: str
    details: dict[str, Any] = Field(default_factory=dict)
    verification_ref: str | None = Field(
        default=None,
        description="Id returned by the tool / system of record after the action",
    )


class OpenQuestion(BaseModel):
    """Unresolved question for the human agent (or to ask the customer)."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    field: str = Field(
        description="Missing or ambiguous field, e.g. amount, date, merchant, transaction_id"
    )
    prompt: str
    priority: QuestionPriority = QuestionPriority.REQUIRED
    language: Literal["es", "pt", "en"] | None = None


class SupportEvidence(BaseModel):
    """Supporting fact for the human — summaries only, never raw transcript text."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_type: EvidenceType
    summary: str = Field(
        ...,
        min_length=1,
        description="Short factual summary. Must NOT be a raw transcript dump.",
    )
    source_ref: str | None = Field(
        default=None,
        description="Opaque reference such as complaint_id, interaction_id, policy_id",
    )
    relevance: str | None = None

    @field_validator("summary")
    @classmethod
    def summary_must_not_look_like_raw_transcript(cls, value: str) -> str:
        lowered = value.lower()
        banned = ("cliente:", "agente:", "customer:", "agent:")
        # Heuristic guard: multi-turn dialogue markers strongly suggest raw transcript.
        hits = sum(1 for token in banned if token in lowered)
        if hits >= 2:
            raise ValueError(
                "support_evidence.summary must not contain raw transcript dialogue; "
                "provide a short factual summary instead"
            )
        return value


class CaseContext(BaseModel):
    """Lightweight case metadata for routing the handoff."""

    model_config = ConfigDict(extra="forbid")

    complaint_id: str | None = None
    customer_id: str | None = None
    case_type: str | None = None
    priority: str | None = None
    status: str | None = None
    sla_breached: bool | None = None
    claimed_amount: float | None = None
    currency: str | None = None
    language: Literal["es", "pt", "en"] | None = None
    reception_channel: str | None = None


class HumanHandoff(BaseModel):
    """Structured package delivered to a human agent on escalate.

    Consumers: frontend handoff UI, data-pipeline exporters, eval harness.
    Out of scope on purpose: raw transcripts, full chat history, chain-of-thought.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SCHEMA_VERSION)
    handoff_id: str
    created_at: str
    reason: str = Field(
        description="Why the graph chose escalate (policy signal, not free-form CoT)"
    )
    case: CaseContext
    verified_transaction: VerifiedTransaction | None = None
    classified_category: ClassifiedCategory
    fraud_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Convenience copy of normalized fraud score (0–1) for UI sorting",
    )
    actions_taken: list[ActionTaken] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    support_evidence: list[SupportEvidence] = Field(default_factory=list)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_handoff_id() -> str:
    return f"HO-{uuid4().hex[:16].upper()}"


def build_example_handoff() -> HumanHandoff:
    """Canonical example grounded in use-case #3 (human-required)."""
    now = "2025-10-29T02:00:00Z"
    return HumanHandoff(
        schema_version=SCHEMA_VERSION,
        handoff_id="HO-EXAMPLEHUMAN001",
        created_at=now,
        reason="priority=Critical AND status=Escalated AND sla_breached=true",
        case=CaseContext(
            complaint_id="CMP-W9KJLENI8RSM8TU99NXZ",
            customer_id="CLI-IDKD41Z51JP1",
            case_type="Complaint",
            priority="Critical",
            status="Escalated",
            sla_breached=True,
            claimed_amount=2984.58,
            currency="COP",
            language="es",
            reception_channel="Call Center",
        ),
        verified_transaction=None,
        classified_category=ClassifiedCategory(
            category="Transactions",
            subcategory="Cargo no reconocido",
            confidence=0.91,
            classifier="rules",
        ),
        fraud_score=None,
        actions_taken=[
            ActionTaken(
                action_id="ACT-001",
                action_type=ActionType.CLASSIFY_CATEGORY,
                status=ActionStatus.SUCCEEDED,
                timestamp=now,
                details={"category": "Transactions", "subcategory": "Cargo no reconocido"},
            ),
            ActionTaken(
                action_id="ACT-002",
                action_type=ActionType.LOOKUP_TRANSACTION,
                status=ActionStatus.FAILED,
                timestamp=now,
                details={"error": "transaction_id not provided by customer"},
            ),
            ActionTaken(
                action_id="ACT-003",
                action_type=ActionType.CREATE_DISPUTE_CASE,
                status=ActionStatus.SUCCEEDED,
                timestamp=now,
                details={"complaint_id": "CMP-W9KJLENI8RSM8TU99NXZ"},
                verification_ref="CMP-W9KJLENI8RSM8TU99NXZ",
            ),
        ],
        open_questions=[
            OpenQuestion(
                question_id="Q-001",
                field="transaction_id",
                prompt="¿Cuál es el ID o fecha exacta de la transacción disputada?",
                priority=QuestionPriority.REQUIRED,
                language="es",
            ),
            OpenQuestion(
                question_id="Q-002",
                field="merchant",
                prompt="¿Recuerda el comercio o canal del cargo no reconocido?",
                priority=QuestionPriority.OPTIONAL,
                language="es",
            ),
        ],
        support_evidence=[
            SupportEvidence(
                evidence_id="EV-001",
                evidence_type=EvidenceType.COMPLAINT_FIELD,
                summary=(
                    "Queja Transactions / Cargo no reconocido por 2984.58 COP; "
                    "prioridad Critical; SLA incumplido."
                ),
                source_ref="CMP-W9KJLENI8RSM8TU99NXZ",
                relevance="primary_case",
            ),
            SupportEvidence(
                evidence_id="EV-002",
                evidence_type=EvidenceType.POLICY_EXCERPT,
                summary=(
                    "Política: casos Critical o con SLA breached deben escalarse "
                    "a agente humano con handoff estructurado."
                ),
                source_ref="policy/rules.py#should_escalate",
                relevance="escalation_rule",
            ),
        ],
    )


def handoff_json_schema() -> dict[str, Any]:
    """JSON Schema (draft 2020-12 style via Pydantic) for external consumers."""
    return HumanHandoff.model_json_schema()
