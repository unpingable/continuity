"""Domain models for continuity.

Three-layer object model:
  1. MemoryObject  — materialized current state
  2. MemoryEvent   — append-only mutation log entry
  3. ReceiptRecord — hash-chained attestation

Plus:
  MemoryLink  — provenance/dependency edge
  PremiseRef  — input-side support reference
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from continuity.util.clock import utcnow
from continuity.util.ids import new_id


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class JsonModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        populate_by_name=True,
        use_enum_values=True,
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MemoryStatus(StrEnum):
    OBSERVED = "observed"
    COMMITTED = "committed"
    REVOKED = "revoked"


class Basis(StrEnum):
    DIRECT_CAPTURE = "direct_capture"
    OPERATOR_ASSERTION = "operator_assertion"
    INFERENCE = "inference"
    IMPORT = "import"
    SYNTHESIS = "synthesis"


class MemoryKind(StrEnum):
    FACT = "fact"
    NOTE = "note"
    DECISION = "decision"
    HYPOTHESIS = "hypothesis"
    SUMMARY = "summary"
    CONSTRAINT = "constraint"
    PROJECT_STATE = "project_state"
    NEXT_ACTION = "next_action"
    EXPERIMENT = "experiment"
    LESSON = "lesson"


class RelianceClass(StrEnum):
    NONE = "none"
    RETRIEVE_ONLY = "retrieve_only"
    ADVISORY = "advisory"
    ACTIONABLE = "actionable"


class EventType(StrEnum):
    OBSERVE = "observe"
    COMMIT = "commit"
    REVOKE = "revoke"
    REPAIR = "repair"
    IMPORT = "import"


class ReceiptType(StrEnum):
    MEMORY_OBSERVE = "memory.observe"
    MEMORY_COMMIT = "memory.commit"
    MEMORY_REVOKE = "memory.revoke"
    MEMORY_REPAIR = "memory.repair"
    MEMORY_IMPORT = "memory.import"


class ImportStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"


class LinkRelation(StrEnum):
    DEPENDS_ON = "depends_on"
    SUPPORTS = "supports"
    DERIVED_FROM = "derived_from"
    IMPLEMENTS = "implements"
    SUPERSEDES = "supersedes"
    INVALIDATES = "invalidates"
    ABOUT = "about"
    # Case-record vocabulary: investigation/debugging structure
    EVIDENCE_FOR = "evidence_for"
    CONFIRMED_BY = "confirmed_by"
    RULED_OUT_BY = "ruled_out_by"


class LinkStrength(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class LinkStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


# ---------------------------------------------------------------------------
# Embedded reference types
# ---------------------------------------------------------------------------

class SourceRef(JsonModel):
    """Reference to the thing this memory is grounded in."""
    ref: str = Field(..., min_length=1, max_length=512)
    kind: str = Field(..., min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=1024)


class ActorRef(JsonModel):
    principal_id: str = Field(..., min_length=1, max_length=255)
    auth_method: str = Field(..., min_length=1, max_length=64)
    principal_ref: str | None = Field(default=None, max_length=255)


class StandingRef(JsonModel):
    token_id: str | None = Field(default=None, max_length=255)
    workload_id: str | None = Field(default=None, max_length=255)
    audience: str | None = Field(default=None, max_length=255)
    assessment_hash: str | None = Field(default=None, max_length=255)


# ---------------------------------------------------------------------------
# Typed content models for known kinds
# ---------------------------------------------------------------------------

class ProjectStateContent(JsonModel):
    project: str = Field(..., min_length=1, max_length=255)
    status: Literal["planned", "active", "blocked", "paused", "done", "superseded"]
    last_touch_summary: str = Field(..., min_length=1, max_length=4000)
    next_action: str | None = Field(default=None, max_length=4000)
    depends_on: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    provisional: bool = False


class NextActionContent(JsonModel):
    project: str = Field(..., min_length=1, max_length=255)
    action: str = Field(..., min_length=1, max_length=4000)
    blocked_on: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)


# ---------------------------------------------------------------------------
# Provenance / dependency
# ---------------------------------------------------------------------------

class PremiseRef(JsonModel):
    """Input-side support reference for observe/commit requests.

    Exactly one of memory_id, receipt_id, or source_ref must be set.
    """
    memory_id: str | None = Field(default=None, min_length=8, max_length=80)
    receipt_id: str | None = Field(default=None, min_length=8, max_length=80)
    source_ref: SourceRef | None = None

    relation: LinkRelation = LinkRelation.DEPENDS_ON
    strength: LinkStrength = LinkStrength.HARD
    note: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_exactly_one_source(self) -> PremiseRef:
        count = sum([
            self.memory_id is not None,
            self.receipt_id is not None,
            self.source_ref is not None,
        ])
        if count != 1:
            raise ValueError(
                "exactly one of memory_id, receipt_id, or source_ref must be set"
            )
        return self


class MemoryLink(JsonModel):
    """Stored provenance/dependency edge.

    dst_memory_id = the memory being justified / linked
    src_*         = the supporting premise or related object
    """
    link_id: str = Field(
        default_factory=lambda: new_id("lnk"), min_length=8, max_length=80
    )

    dst_memory_id: str = Field(..., min_length=8, max_length=80)

    src_memory_id: str | None = Field(default=None, min_length=8, max_length=80)
    src_receipt_id: str | None = Field(default=None, min_length=8, max_length=80)
    src_ref: SourceRef | None = None

    relation: LinkRelation
    strength: LinkStrength = LinkStrength.HARD
    status: LinkStatus = LinkStatus.ACTIVE
    note: str | None = Field(default=None, max_length=1024)

    created_at: datetime = Field(default_factory=utcnow)
    created_by_event_id: str | None = Field(default=None, min_length=8, max_length=80)

    revoked_at: datetime | None = None
    revoked_by_event_id: str | None = Field(default=None, min_length=8, max_length=80)

    @model_validator(mode="after")
    def validate_exactly_one_source(self) -> MemoryLink:
        count = sum([
            self.src_memory_id is not None,
            self.src_receipt_id is not None,
            self.src_ref is not None,
        ])
        if count != 1:
            raise ValueError(
                "exactly one of src_memory_id, src_receipt_id, or src_ref must be set"
            )
        return self


# ---------------------------------------------------------------------------
# Core domain objects
# ---------------------------------------------------------------------------

class MemoryObject(JsonModel):
    """Materialized current state of a memory object."""
    memory_id: str = Field(
        default_factory=lambda: new_id("mem"), min_length=8, max_length=80
    )
    scope: str = Field(..., min_length=1, max_length=255)
    kind: MemoryKind
    basis: Basis
    status: MemoryStatus = MemoryStatus.OBSERVED
    reliance_class: RelianceClass = RelianceClass.NONE
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    content: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None

    supersedes: str | None = Field(default=None, max_length=80)
    revoked_by: str | None = Field(default=None, max_length=80)

    created_by: ActorRef | None = None
    approved_by: ActorRef | None = None

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("scope must not be empty")
        return value

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("content must not be empty")
        return value

    @field_validator("source_refs")
    @classmethod
    def validate_source_refs_unique(cls, value: list[SourceRef]) -> list[SourceRef]:
        seen: set[tuple[str, str]] = set()
        for item in value:
            key = (item.kind, item.ref)
            if key in seen:
                raise ValueError(f"duplicate source_ref: {item.kind}:{item.ref}")
            seen.add(key)
        return value


class MemoryEvent(JsonModel):
    """Append-only mutation log entry for a memory object."""
    event_id: str = Field(
        default_factory=lambda: new_id("evt"), min_length=8, max_length=80
    )
    memory_id: str = Field(..., min_length=8, max_length=80)
    event_type: EventType

    actor: ActorRef | None = None
    standing: StandingRef | None = None

    receipt_id: str = Field(..., min_length=8, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str | None = Field(default=None, max_length=255)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload must not be empty")
        return value


class ReceiptRecord(JsonModel):
    """Stored receipt with hash-chain linkage."""
    receipt_id: str = Field(
        default_factory=lambda: new_id("rcpt"), min_length=8, max_length=80
    )
    receipt_type: ReceiptType
    hash: str = Field(..., min_length=16, max_length=255)
    prev_hash: str | None = Field(default=None, min_length=16, max_length=255)
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("content must not be empty")
        return value


class SpoolImport(JsonModel):
    import_id: str = Field(
        default_factory=lambda: new_id("imp"), min_length=8, max_length=80
    )
    source: str = Field(..., min_length=1, max_length=255)
    external_ref: str | None = Field(default=None, max_length=512)
    status: ImportStatus = ImportStatus.PENDING
    reason: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=utcnow)
    applied_at: datetime | None = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ObserveMemoryRequest(JsonModel):
    scope: str = Field(..., min_length=1, max_length=255)
    kind: MemoryKind
    basis: Basis
    content: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)
    premises: list[PremiseRef] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    expires_at: datetime | None = None
    supersedes: str | None = Field(default=None, max_length=80)
    actor: ActorRef | None = None
    standing: StandingRef | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)


class ObserveMemoryResponse(JsonModel):
    memory: MemoryObject
    event: MemoryEvent
    receipt: ReceiptRecord
    links: list[MemoryLink] = Field(default_factory=list)


class CommitMemoryRequest(JsonModel):
    memory_id: str = Field(..., min_length=8, max_length=80)
    reliance_class: RelianceClass = RelianceClass.RETRIEVE_ONLY
    approved_by: ActorRef | None = None
    standing: StandingRef | None = None
    supersedes: str | None = Field(default=None, max_length=80)
    expires_at: datetime | None = None
    note: str | None = Field(default=None, max_length=4000)
    premises: list[PremiseRef] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=255)


class CommitMemoryResponse(JsonModel):
    memory: MemoryObject
    event: MemoryEvent
    receipt: ReceiptRecord
    links: list[MemoryLink] = Field(default_factory=list)


class RevokeMemoryRequest(JsonModel):
    memory_id: str = Field(..., min_length=8, max_length=80)
    reason: str = Field(..., min_length=1, max_length=4000)
    revoked_by: ActorRef | None = None
    standing: StandingRef | None = None
    replacement_memory_id: str | None = Field(default=None, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=255)


class RevokeMemoryResponse(JsonModel):
    memory: MemoryObject
    event: MemoryEvent
    receipt: ReceiptRecord


class RepairMemoryRequest(JsonModel):
    memory_id: str = Field(..., min_length=8, max_length=80)
    target_event_id: str | None = Field(default=None, max_length=80)
    target_receipt_id: str | None = Field(default=None, max_length=80)
    reason: str = Field(..., min_length=1, max_length=4000)
    patch: dict[str, Any] = Field(default_factory=dict)
    actor: ActorRef | None = None
    standing: StandingRef | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)

    @field_validator("patch")
    @classmethod
    def validate_patch(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("patch must not be empty")
        return value


class RepairMemoryResponse(JsonModel):
    event: MemoryEvent
    receipt: ReceiptRecord


class QueryMemoryRequest(JsonModel):
    scope: str | None = Field(default=None, max_length=255)
    kind: MemoryKind | None = None
    status: MemoryStatus | None = None
    basis: Basis | None = None
    reliance_class: RelianceClass | None = None
    include_expired: bool = False
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class QueryMemoryResponse(JsonModel):
    items: list[MemoryObject]
    total: int


class ExplainMemoryResponse(JsonModel):
    memory: MemoryObject
    events: list[MemoryEvent]
    receipts: list[ReceiptRecord]
    premises: list[MemoryLink] = Field(default_factory=list)
    dependents: list[MemoryLink] = Field(default_factory=list)
    rely_ok: bool
    rely_reason: str


# ---------------------------------------------------------------------------
# Case bundle (derived view)
# ---------------------------------------------------------------------------

class GetCaseRequest(JsonModel):
    """Request for the derived case bundle for a scope."""
    scope: str = Field(..., min_length=1, max_length=255)
    include_expired: bool = False


class CaseItem(JsonModel):
    """A single memory inside a case bundle, paired with its rely state."""
    memory: MemoryObject
    rely_ok: bool
    rely_reason: str


class CaseBundle(JsonModel):
    """Derived view of all memories in a case scope.

    A case is identified by its scope. The bundle is computed on demand
    from existing memories — nothing is persisted at the case level. Items
    in each bucket are ordered chronologically by created_at, so reading
    top to bottom roughly follows the investigation timeline.

    The bundle is a navigation aid; it is not itself authoritative. Each
    embedded item carries its own rely_ok flag, and code that wants to act
    on a finding should rely on the underlying fact, not the bundle.
    """
    scope: str
    title: str | None = None
    summary: CaseItem | None = None

    facts: list[CaseItem] = Field(default_factory=list)
    hypotheses: list[CaseItem] = Field(default_factory=list)
    experiments: list[CaseItem] = Field(default_factory=list)
    lessons: list[CaseItem] = Field(default_factory=list)
    decisions: list[CaseItem] = Field(default_factory=list)
    constraints: list[CaseItem] = Field(default_factory=list)
    notes: list[CaseItem] = Field(default_factory=list)
    project_states: list[CaseItem] = Field(default_factory=list)
    next_actions: list[CaseItem] = Field(default_factory=list)
    other: list[CaseItem] = Field(default_factory=list)

    total_memories: int = 0
    last_touch: datetime | None = None
