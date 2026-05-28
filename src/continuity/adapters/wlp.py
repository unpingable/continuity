"""WLP persistence adapter — custody-preserving storage for WLP artifacts.

Implementation of the V1 surface specified in
`docs/gaps/WLP_PERSISTENCE_ADAPTER_GAP.md` (graduated from candidate
2026-05-28 under MVP-A forcing pressure).

The adapter writes WLP HandlingReceipt and AuthorizationReceipt
envelopes into continuity and reads them out. It preserves the
WLP-provided `artifact_hash` verbatim; it does NOT recompute the hash
on store (per invariant 7: hash-chained ≠ ratified — recomputation
implies re-validation).

Library only. No CLI, no MCP, no transport surface (invariant 11:
persistence ≠ transport). Callers wire the adapter into their own
ingest pipelines.

The twelve invariants live in the gap-spec and are referenced in the
refusal-shaped checks below. Each refusal point cites the relevant
invariant by number.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from continuity.api.models import (
    ActorRef,
    Basis,
    ImportMemoryRequest,
    MemoryKind,
    MemoryObject,
    MemoryStatus,
    RelianceClass,
    SourceRef,
)
from continuity.store.sqlite import SQLiteStore
from continuity.util.hashing import content_hash

__all__ = [
    "WLPArtifactStored",
    "WLPNonCanonicalInputError",
    "WLPHashMismatchError",
    "store_wlp_artifact",
    "readback_wlp_artifact",
    "verify_wlp_artifact_hash",
    "wlp_canonical_for_hash",
]


# Fields inside `custody` that WLP zeros before computing artifact_hash —
# these fields are self-referential (artifact_hash contains its own hash;
# receipt_hash and signature reference the same artifact). The hash is
# computed over the envelope with these fields nulled out, then the
# computed value is written back into artifact_hash.
_SELF_REFERENTIAL_CUSTODY_FIELDS = ("artifact_hash", "receipt_hash", "signature")


class WLPNonCanonicalInputError(ValueError):
    """Raised when input bytes are not in canonical JSON form.

    The adapter does not silently re-canonicalize input — the caller
    is responsible for delivering canonical bytes. This is storage
    hygiene, not WLP semantic validation (invariant 1: stored ≠ valid).
    """


class WLPHashMismatchError(ValueError):
    """Raised when verify_wlp_artifact_hash detects a hash mismatch.

    Storage-integrity failure, not WLP semantic validation. Indicates
    the readback bytes do not hash to the expected WLP artifact_hash.
    """


@dataclass(frozen=True)
class WLPArtifactStored:
    """Result of a successful store_wlp_artifact call.

    Carries continuity-side identifiers (memory_id, receipt_id) and
    WLP-side identity preserved verbatim (artifact_hash, kind,
    causal_parents). Consumers can use either side without continuity
    making claims about WLP validity or vice versa.
    """

    memory_id: str
    receipt_id: str
    wlp_artifact_hash: str
    wlp_kind: str
    causal_parents: list[str]
    already_imported: bool


def wlp_canonical_for_hash(envelope: dict[str, Any]) -> bytes:
    """Produce the WLP-compatible canonical form used for artifact_hash.

    WLP's canonicalization for the hash field: zero
    `custody.{artifact_hash, receipt_hash, signature}`, then JCS-style
    JSON (sorted keys, compact separators, UTF-8). The artifact_hash
    field cannot contain its own hash — that would be circular —
    so WLP excludes these self-referential fields before hashing.

    This function is used by verify_wlp_artifact_hash only. The
    store path does NOT call it on store (invariant 7).
    """
    body = copy.deepcopy(envelope)
    custody = body.get("custody")
    if isinstance(custody, dict):
        for field in _SELF_REFERENTIAL_CUSTODY_FIELDS:
            if field in custody:
                custody[field] = None
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_canonical_jcs(envelope_bytes: bytes) -> bool:
    """Return True if envelope_bytes round-trip to themselves under JCS."""
    try:
        obj = json.loads(envelope_bytes)
    except json.JSONDecodeError:
        return False
    re_canon = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return re_canon == envelope_bytes


def _content_addressed_memory_id(wlp_artifact_hash: str) -> str:
    """Derive a deterministic memory_id from the WLP artifact_hash.

    Same envelope → same memory_id → natural idempotency through
    import_memory's existing (memory_id, content_hash) check.
    """
    hex_part = wlp_artifact_hash.removeprefix("sha256:")
    if len(hex_part) < 32:
        raise ValueError(
            f"wlp_artifact_hash too short: {wlp_artifact_hash!r}; "
            "expected 'sha256:<64-hex-chars>'"
        )
    return f"mem_wlp_{hex_part}"


def store_wlp_artifact(
    store: SQLiteStore,
    envelope_bytes: bytes,
    wlp_artifact_hash: str,
    *,
    scope: str = "wlp",
    source_store_id: str = "wlp",
    source_path: str | None = None,
    actor: ActorRef | None = None,
) -> WLPArtifactStored:
    """Persist a WLP HandlingReceipt or AuthorizationReceipt envelope.

    Inputs:
      envelope_bytes      — canonical JSON bytes (sort_keys, compact)
                            of the WLP envelope. Must already be
                            canonical; the adapter does not silently
                            re-canonicalize.
      wlp_artifact_hash   — the WLP-provided 'sha256:<64-hex>' hash.
                            Preserved verbatim. NOT recomputed
                            (invariant 7).

    Refusal-shaped checks (each cites the relevant gap invariant):
      - WLPNonCanonicalInputError if envelope_bytes does not survive a
        JCS round-trip unchanged. (Storage hygiene; not WLP validation.
        Invariant 1: stored ≠ valid.)

    Storage shape (Option B from MVP_A_SLICE_5_PACKET, no schema
    migration):
      - memory_object with basis=IMPORT, kind=NOTE, status=OBSERVED,
        reliance_class=NONE — invariant 6: imported ≠ accepted;
        invariant 12: receipt store ≠ reliance engine.
      - memory.import receipt — continuity's own chain hash, not the
        WLP hash. WLP artifact_hash is recorded in source_ref (the
        receipt's content) and source_refs (memory metadata).

    Returns WLPArtifactStored with both continuity-side and WLP-side
    identifiers. Continuity does not claim WLP validity; the WLP
    side does not claim continuity's chain authority.
    """
    if not _is_canonical_jcs(envelope_bytes):
        raise WLPNonCanonicalInputError(
            "envelope_bytes are not in JCS canonical form "
            "(sort_keys=True, separators=(',', ':')). The adapter "
            "does not silently re-canonicalize input — invariant 1: "
            "stored ≠ valid."
        )

    envelope: dict[str, Any] = json.loads(envelope_bytes)
    wlp_kind: str = str(envelope.get("kind", ""))
    causal_parents: list[str] = list(
        envelope.get("custody", {}).get("causal_parents", []) or []
    )

    memory_id = _content_addressed_memory_id(wlp_artifact_hash)

    source_refs: list[SourceRef] = [
        SourceRef(
            kind="wlp_artifact_hash",
            ref=wlp_artifact_hash,
            note=wlp_kind,
        ),
    ]
    if source_path:
        source_refs.append(SourceRef(kind="file", ref=source_path, note=""))

    candidate = MemoryObject(
        memory_id=memory_id,
        scope=scope,
        kind=MemoryKind.NOTE,
        basis=Basis.IMPORT,
        status=MemoryStatus.OBSERVED,
        reliance_class=RelianceClass.NONE,
        confidence=0.5,
        content=envelope,
        source_refs=source_refs,
    )
    expected_content_hash = content_hash(candidate)

    req = ImportMemoryRequest(
        source_store_id=source_store_id,
        source_ref=wlp_artifact_hash,
        memory_id=memory_id,
        scope=scope,
        kind=MemoryKind.NOTE,
        basis=Basis.IMPORT,
        content=envelope,
        reliance_class=RelianceClass.NONE,
        confidence=0.5,
        source_refs=source_refs,
        status=MemoryStatus.OBSERVED,
        expected_content_hash=expected_content_hash,
        actor=actor,
    )
    resp = store.import_memory(req)

    return WLPArtifactStored(
        memory_id=memory_id,
        receipt_id=resp.receipt.receipt_id,
        wlp_artifact_hash=wlp_artifact_hash,
        wlp_kind=wlp_kind,
        causal_parents=causal_parents,
        already_imported=resp.already_imported,
    )


def readback_wlp_artifact(store: SQLiteStore, memory_id: str) -> bytes:
    """Read a stored WLP envelope back as canonical JSON bytes.

    Returns byte-identical canonical bytes when the envelope was
    stored via store_wlp_artifact (which refuses non-canonical input;
    the dict survives a SQLite text round-trip and JCS re-serializes
    deterministically).

    Uses the existing get_memory path — invariant 11: persistence ≠
    transport, no new readback surface.
    """
    memory = store.get_memory(memory_id)
    envelope = memory.content
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_wlp_artifact_hash(
    envelope_bytes: bytes,
    expected_artifact_hash: str,
) -> bool:
    """Recompute the WLP artifact_hash over envelope_bytes and compare.

    This is storage-integrity verification: did the readback bytes
    hash to the value WLP claimed at issue time?

    NOT a validation of WLP semantics. A passing result does NOT mean
    the artifact's claim is true — only that the bytes are the bytes
    WLP signed (invariant 1: stored ≠ valid; invariant 8: WLP-valid
    envelope ≠ authorized action).

    Returns True on match, False on mismatch. Callers may treat False
    as a storage-integrity failure (custody compromise) and raise.
    """
    try:
        envelope = json.loads(envelope_bytes)
    except json.JSONDecodeError:
        return False
    canon = wlp_canonical_for_hash(envelope)
    computed = "sha256:" + hashlib.sha256(canon).hexdigest()
    return computed == expected_artifact_hash
