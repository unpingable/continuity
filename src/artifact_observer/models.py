"""The observation claim shape — the observer's own, not continuity's.

An ArtifactObservation is deliberately NOT a MemoryObject. An observation is not
a memory; the two are made commensurable at the MapSkew comparison layer (a later
gap), never by sharing a schema here. This module imports nothing from continuity.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SubjectKind(StrEnum):
    """What kind of artifact was observed. V0 implements FILE; the rest are
    reserved so the enum does not churn when they earn a forcing case."""

    FILE = "file"
    SYMBOL = "symbol"            # reserved
    DOC_SECTION = "doc_section"  # reserved
    ROUTE = "route"             # reserved


class ClaimKind(StrEnum):
    """The shape of the claim the observation makes about the subject."""

    EXISTS = "exists"       # the subject is present (claim_value: "true"/"false")
    CONTAINS = "contains"   # the subject contains a needle (claim_value: the match)
    DECLARES = "declares"   # the subject declares a token (a narrowed contains)
    OMITS = "omits"         # the subject does NOT contain a needle


class ObserverSourceRef(BaseModel):
    """Line-of-sight for an observation: enough to reproduce the scan. The
    observer's own ref type — not continuity.api.models.SourceRef."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo: str                         # repo root (basename or path)
    path: str                         # path within the repo
    content_digest: str | None = None  # sha256 of the observed bytes, when readable
    commit: str | None = None          # git HEAD when a worktree resolves; else None
    line: int | None = None            # 1-indexed line of a match, when applicable


class ArtifactObservation(BaseModel):
    """One bounded, read-only claim about an artifact's current state.

    Carries `observed_at` (which becomes a memory's `source_observed_at` if one is
    later formed) and a reproducible `source_ref`. `can_testify=False` is a
    first-class honest outcome — refusal is evidence, not silence — and is
    distinct from observed *absence* (e.g. EXISTS with claim_value "false")."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    subject: str
    subject_kind: SubjectKind
    claim_kind: ClaimKind
    claim_value: str | None = None
    observed_at: datetime
    source_ref: ObserverSourceRef
    can_testify: bool = True
    cannot_testify_reason: str | None = None
    observer_version: str = Field(default="0.0.1")
