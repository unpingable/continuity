"""Content hashing for receipts and cross-DB memory identity.

Three hash functions, all sha256 over canonical JSON:

  receipt_hash   — receipt chain linkage (prev_hash + content)
  request_hash   — refusal-receipt fingerprint for a denied request
  content_hash   — portable cross-DB identity for a memory's committed payload
  state_hash     — content_hash + local posture (status, revoked_by)

content_hash and state_hash split intentionally: content drift and status
drift are different failures (see docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md).
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, Any

from continuity.util.jsoncanon import canonical_json

if TYPE_CHECKING:
    from continuity.api.models import MemoryObject


def receipt_hash(
    *,
    receipt_type: str,
    prev_hash: str | None,
    content: dict[str, Any],
) -> str:
    """Compute SHA-256 hash for a receipt, chaining from prev_hash."""
    material = {
        "receipt_type": receipt_type,
        "prev_hash": prev_hash,
        "content": content,
    }
    return sha256(canonical_json(material).encode("utf-8")).hexdigest()


def request_hash(payload: Any) -> str:
    """SHA-256 over the canonical JSON of a request payload.

    Used by refusal receipts to record what the operator tried to do without
    trusting the operator-supplied identifiers. The hash is deterministic
    across stores, so two databases handed the same canonical request
    payload will record the same request_hash.
    """
    return "sha256:" + sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def content_hash(memory: "MemoryObject") -> str:
    """Portable hash of a memory's committed payload, stable across stores.

    Hashes the subset that two stores agree on when they hold "the same
    memory at the same version": `(source_memory_id, scope, kind, content,
    reliance_class, supersedes)`.

    Notes:
      - `source_memory_id` is the canonical cross-DB identity (per
        CROSS_SCOPE_REFERENCE_GAP invariant 1). It is named `source_*`
        in the hash payload to make its role explicit and prevent a
        future local-IDs-poisoning-portable-hashes mistake.
      - `status` is intentionally OUT — revocation is state, not content.
        See state_hash() for the posture half.
      - `confidence`, timestamps, actor/standing fields, and source_refs
        are local recording metadata, not portable identity, so they do
        not appear here.
    """
    payload = {
        "source_memory_id": memory.memory_id,
        "scope": memory.scope,
        "kind": str(memory.kind),
        "content": memory.content,
        "reliance_class": str(memory.reliance_class),
        "supersedes": memory.supersedes,
    }
    return "sha256:" + sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def state_hash(memory: "MemoryObject") -> str:
    """Local posture hash: content_hash + (status, revoked_by).

    Same content + same status + same revoked_by -> same state_hash. When
    a memory is revoked, its content_hash is unchanged but its state_hash
    flips. Explain uses this split to label drift accurately: 'content
    drift' (the doctrine was rewritten) vs 'state drift' (the doctrine
    was revoked after I cited it).
    """
    payload = {
        "content_hash": content_hash(memory),
        "status": str(memory.status),
        "revoked_by": memory.revoked_by,
    }
    return "sha256:" + sha256(canonical_json(payload).encode("utf-8")).hexdigest()
