"""Declaration export — a deliberately humiliating projection of what Continuity holds.

`continuity.declaration_export.v0` is the contract Continuity OWNS and a consumer
(e.g. the Spine read plane) later locates and packages. The export says, and says
*only*:

    here are declared refs;
    here is how Continuity holds them (quoted status + quoted metadata);
    here is export provenance;
    here is an export digest over the declarations.

It must NOT say: these are authoritative / current / canonical / ratified / doctrine,
or that one declaration supersedes another *as truth*. Even though Continuity knows
richer things internally (reliance_class, supersedes pointers, commit status), this
export surface is intentionally boring: a status is emitted as a **quoted source
status**, never a universal fact. The standing tag on every status spells it out:
``quoted_continuity_status_not_spine_standing``.

Two guarantees make this mechanical, not aspirational:

- ``source_metadata`` is an **allowlist** (`_QUOTED_METADATA_FIELDS`) — arbitrary
  content keys cannot flow into the export, so a memory cannot smuggle an authority
  field through its free-form ``content``.
- :func:`build_declaration_export` runs a self-check (`_assert_no_forbidden_fields`)
  that refuses to emit an export carrying any forbidden authority/recency field name.

Determinism: the ``export_id`` is a sha256 over the *declarations* (and the schema
tag) only — ``exported_at`` and ``source`` provenance are excluded, so the same held
declarations always produce the same export_id regardless of when or where exported.
The clock is resolved at the boundary (the CLI), never inside the builder — matching
Continuity's time discipline.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from pydantic import ConfigDict, Field

from continuity.api.models import JsonModel, MemoryObject
from continuity.util.clock import to_isoformat
from continuity.util.jsoncanon import canonical_json

SCHEMA = "continuity.declaration_export.v0"

# Stamped on every quoted status so no reader can mistake it for the consumer's
# own standing. Continuity quotes its status; it does not confer authority.
SOURCE_STANDING = "quoted_continuity_status_not_spine_standing"

# Content keys that name a locatable artifact. A memory is a *declaration* iff its
# content carries a non-empty ref; everything else is excluded (loudly, never dropped).
DEFAULT_REF_KEY = "ref"
DEFAULT_PATH_KEY = "path"

# The ONLY memory fields quoted into source_metadata — an allowlist, so free-form
# content cannot inject extra (possibly authority-shaped) fields. Descriptive only.
_QUOTED_METADATA_FIELDS = ("kind", "reliance_class", "scope", "confidence", "supersedes")

# Field NAMES this export may never carry. Authority/recency words that would turn a
# quoted declaration into a verdict. NB: bare ``supersedes`` is NOT here — it is a
# genuine Continuity field, quoted as metadata; ``supersedes_as_truth`` (the *claim*
# that one declaration overrides another) is what is forbidden.
FORBIDDEN_EXPORT_FIELDS = frozenset({
    "latest", "current", "canonical", "authoritative", "authority",
    "ratified", "supersedes_as_truth", "doctrine",
})


class ExportError(ValueError):
    """The export could not be produced as a humiliating, authority-free projection
    (e.g. a forbidden authority field reached the serialized export). A ValueError so
    the CLI's existing handler surfaces it cleanly."""


class SourceStatus(JsonModel):
    """A Continuity status, quoted — never the consumer's standing. ``value`` is the
    raw status (observed/committed/revoked); ``standing`` always carries the tag that
    says, on its face, 'this is not standing'."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, use_enum_values=True)

    value: str
    standing: str = SOURCE_STANDING


class DeclarationEntry(JsonModel):
    """One declared ref. The status is quoted; the metadata is an allowlisted quote;
    neither is an assertion that the ref is true, current, or governed."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, use_enum_values=True)

    ref: str
    path: str | None = None
    declared_at: str | None = None
    source_status: SourceStatus
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class ExportSource(JsonModel):
    """Export provenance — who produced this export. Excluded from ``export_id``
    (provenance documents production, it does not fork content identity)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, use_enum_values=True)

    tool: str = "continuity"
    version: str
    repo: str | None = None
    commit: str | None = None


class DeclarationExport(JsonModel):
    """A `continuity.declaration_export.v0` document. ``export_id`` digests the
    declarations (and schema tag) only — deterministic regardless of when/where
    exported."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, use_enum_values=True)

    # Attribute is `schema_id`; the wire key is `schema` (avoids shadowing
    # BaseModel.schema while keeping the contract key clean).
    schema_id: str = Field(
        default=SCHEMA, serialization_alias="schema", validation_alias="schema"
    )
    export_id: str
    exported_at: str
    source: ExportSource
    declarations: list[DeclarationEntry]

    def canonical_dict(self) -> dict[str, Any]:
        """The wire form: keys by alias (so the schema field is `schema`)."""
        return self.model_dump(mode="json", by_alias=True)


class ExcludedMemory(JsonModel):
    """A memory left out of the export, with a reason — no silent drops."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, use_enum_values=True)

    memory_id: str
    reason: str


def _quote_metadata(memory: MemoryObject) -> dict[str, Any]:
    """Allowlisted, stringified quote of Continuity's own fields — descriptive,
    never authority. Absent/None fields are omitted."""
    out: dict[str, Any] = {}
    for field in _QUOTED_METADATA_FIELDS:
        value = getattr(memory, field, None)
        if value is not None:
            out[field] = str(value)
    return out


def compute_export_id(declarations: list[DeclarationEntry]) -> str:
    """sha256 over the schema tag + declarations only. Excludes ``exported_at`` and
    ``source`` so the digest is content-addressed: same declarations -> same id."""
    body = {
        "schema": SCHEMA,
        "declarations": [d.model_dump(mode="json", by_alias=True) for d in declarations],
    }
    return "sha256:" + sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _all_keys_lower(obj: object):
    """Yield every mapping key (lowercased) anywhere in a nested structure — keys
    only, never values, so a ref value like 'repo:canonical-note.md' is not a hit."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k).lower()
            yield from _all_keys_lower(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _all_keys_lower(item)


def _assert_no_forbidden_fields(export: DeclarationExport) -> None:
    hits = sorted({k for k in _all_keys_lower(export.canonical_dict()) if k in FORBIDDEN_EXPORT_FIELDS})
    if hits:
        raise ExportError(
            f"declaration export carries forbidden authority field(s) {hits!r}; an "
            "export quotes statuses and provenance, it does not assert authority, "
            "recency, or supersession-as-truth"
        )


def build_declaration_export(
    memories: list[MemoryObject],
    *,
    exported_at: str,
    source: ExportSource,
    ref_key: str = DEFAULT_REF_KEY,
    path_key: str = DEFAULT_PATH_KEY,
) -> tuple[DeclarationExport, list[ExcludedMemory]]:
    """Project memories into a `continuity.declaration_export.v0`. Pure: the clock is
    not called here — ``exported_at`` is resolved by the caller (the boundary).

    A memory contributes a declaration iff its ``content`` carries a non-empty
    ``ref_key``; otherwise it is excluded with a reason (no silent drops). Declarations
    are sorted by (ref, path) for determinism.
    """
    declarations: list[DeclarationEntry] = []
    excluded: list[ExcludedMemory] = []

    for memory in memories:
        content = memory.content or {}
        ref = content.get(ref_key)
        if not (isinstance(ref, str) and ref.strip()):
            excluded.append(ExcludedMemory(memory_id=memory.memory_id, reason="no_locatable_ref"))
            continue
        path = content.get(path_key)
        declarations.append(
            DeclarationEntry(
                ref=ref.strip(),
                path=path.strip() if isinstance(path, str) and path.strip() else None,
                declared_at=to_isoformat(memory.created_at),
                source_status=SourceStatus(value=str(memory.status)),
                source_metadata=_quote_metadata(memory),
            )
        )

    declarations.sort(key=lambda d: (d.ref, d.path or ""))
    export = DeclarationExport(
        export_id=compute_export_id(declarations),
        exported_at=exported_at,
        source=source,
        declarations=declarations,
    )
    _assert_no_forbidden_fields(export)
    return export, excluded
