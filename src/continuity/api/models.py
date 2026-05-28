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
from typing import Any, ClassVar, Literal

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
    # Policy-denied write attempt. No memory row, no memory event — just
    # a chained receipt so denied writes are audit-visible (per
    # docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md / plan Phase 0.3 amendment).
    MEMORY_REFUSED = "memory.refused"


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

    # When premise targets an imported memory, pinning captures the
    # content_hash current at reliance time. Future explain compares pin
    # vs. current local content_hash to surface drift; the rely path
    # remains local (see docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md inv. 7).
    # sha256:<64 hex> is 71 chars; allow a bit of slack.
    pinned_content_hash: str | None = Field(default=None, max_length=128)

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

    # Mirrors PremiseRef.pinned_content_hash: the content_hash captured at
    # reliance creation time. Unpinned premises (None) read current state.
    pinned_content_hash: str | None = Field(default=None, max_length=128)

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
    """Fix a recording error in an existing memory.

    Repair is intentionally narrow: it can correct **metadata and content**
    (typos, missing source_refs, miscalibrated confidence) but cannot change
    fields that affect rely semantics (scope/kind/basis/status/reliance_class,
    expiration, supersession, premises, revocation pointer). Those transitions
    go through observe/commit/revoke/supersede, which leave a different
    audit shape.

    The intent: repair = "I wrote this down wrong, fix the record."
    Anything that would change what downstream callers may rely on is a
    different verb.
    """
    memory_id: str = Field(..., min_length=8, max_length=80)
    target_event_id: str | None = Field(default=None, max_length=80)
    target_receipt_id: str | None = Field(default=None, max_length=80)
    reason: str = Field(..., min_length=1, max_length=4000)
    patch: dict[str, Any] = Field(default_factory=dict)
    actor: ActorRef | None = None
    standing: StandingRef | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)

    # Keys that a repair patch may set. Any other key raises a validation
    # error directing the operator to supersede or revoke+recommit.
    ALLOWED_PATCH_KEYS: ClassVar[tuple[str, ...]] = (
        "content",
        "source_refs",
        "confidence",
    )

    @field_validator("patch")
    @classmethod
    def validate_patch(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("patch must not be empty")
        allowed = set(cls.ALLOWED_PATCH_KEYS)
        forbidden = set(value.keys()) - allowed
        if forbidden:
            # Sorted for deterministic error messages.
            joined = ", ".join(sorted(forbidden))
            raise ValueError(
                f"repair patch may only set {sorted(allowed)}; got disallowed "
                f"key(s) {{{joined}}}. Use supersede for "
                f"scope/kind/reliance changes, or revoke+recommit for "
                f"status/basis changes. Premise edits require an explicit "
                f"commit that appends new premises."
            )
        return value


class RepairMemoryResponse(JsonModel):
    memory: MemoryObject
    event: MemoryEvent
    receipt: ReceiptRecord


class ImportMemoryRequest(JsonModel):
    """Pull a memory from a source store into the local store.

    The portable payload (`memory_id`, `scope`, `kind`, `basis`, `content`,
    `reliance_class`, `supersedes`) plus the expected `content_hash` are
    verified before any local row is created. A mismatch aborts the import.

    The import is recorded as a `memory.imported` event with a hash-chained
    `memory.import` receipt, so the local audit trail shows when and from
    where this cross-scope reference entered (per
    docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md invariants 4-6).
    """
    source_store_id: str = Field(..., min_length=1, max_length=255)
    source_ref: str | None = Field(default=None, max_length=512)

    # Portable payload — these fields are hashed into content_hash.
    memory_id: str = Field(..., min_length=8, max_length=80)
    scope: str = Field(..., min_length=1, max_length=255)
    kind: MemoryKind
    basis: Basis
    content: dict[str, Any] = Field(default_factory=dict)
    reliance_class: RelianceClass = RelianceClass.NONE
    supersedes: str | None = Field(default=None, max_length=80)

    # Optional local recording metadata (does not affect content_hash).
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_refs: list[SourceRef] = Field(default_factory=list)
    expires_at: datetime | None = None
    status: MemoryStatus = MemoryStatus.COMMITTED

    # The caller asserts the content hash. The store recomputes and refuses
    # on mismatch so a bad payload can't slip through.
    expected_content_hash: str = Field(..., min_length=16, max_length=255)

    actor: ActorRef | None = None
    standing: StandingRef | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)


class ImportMemoryResponse(JsonModel):
    memory: MemoryObject
    event: MemoryEvent
    receipt: ReceiptRecord
    spool_import_id: str
    # True if the import was idempotent — memory already present locally at
    # the same content_hash, and no new event/receipt was emitted.
    already_imported: bool = False


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


class ImportedPremiseStatus(JsonModel):
    """Local-only diagnostic for a premise pointing at an imported memory.

    Surfaces drift between the content_hash pinned at reliance time and
    the current local copy, plus the imported memory's current state.
    Per docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md and the plan's Phase 1.4
    amendment: explain is local-only by default — source reachability is
    a separate operation, not folded in here.
    """
    link_id: str
    src_memory_id: str
    pinned_content_hash: str | None = None
    current_content_hash: str
    # 'match' when pinned == current; 'drift' when they differ; 'unpinned'
    # when no pin was recorded on the link.
    content_status: Literal["match", "drift", "unpinned"]
    # Local state of the imported memory at evaluation_time.
    # 'observed' | 'committed' | 'revoked' | 'expired'
    state: str
    # Provenance from the local import receipt — passthrough only, no
    # network call to confirm the source still has this version.
    source_store_id: str | None = None
    imported_at: datetime | None = None


class ExplainMemoryResponse(JsonModel):
    memory: MemoryObject
    events: list[MemoryEvent]
    receipts: list[ReceiptRecord]
    premises: list[MemoryLink] = Field(default_factory=list)
    dependents: list[MemoryLink] = Field(default_factory=list)
    rely_ok: bool
    rely_reason: str
    # The wall-clock moment used to compute rely_ok / expiry. Captured so
    # an audit can reconstruct the decision context. Per the time-discipline
    # gap: any clock read that affects whether memory binds must be explicit
    # or surfaced in the response.
    evaluation_time: datetime | None = None
    # One entry per premise whose src_memory_id is locally imported
    # (basis=import). Surfaces content drift and state changes against the
    # pinned hash. Empty when no premises target imported memories.
    imported_premises: list[ImportedPremiseStatus] = Field(default_factory=list)


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
