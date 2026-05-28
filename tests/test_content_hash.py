"""Test content_hash + state_hash split.

The split is load-bearing for cross-host pinned imports
(docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md): two stores holding the same
memory at the same version must compute the same content_hash. When the
memory is revoked locally, content_hash must NOT change — that's what the
state_hash captures.

Keeper: content drift and status drift are different failures.
"""

from continuity.api.models import (
    Basis,
    MemoryKind,
    MemoryObject,
    MemoryStatus,
    RelianceClass,
)
from continuity.util.hashing import content_hash, state_hash


def _committed_fact(**overrides) -> MemoryObject:
    base = dict(
        memory_id="mem_canonical_xyz_0000000000",
        scope="global",
        kind=MemoryKind.LESSON,
        basis=Basis.OPERATOR_ASSERTION,
        status=MemoryStatus.COMMITTED,
        reliance_class=RelianceClass.ADVISORY,
        content={"lesson": "what we learned"},
    )
    base.update(overrides)
    return MemoryObject(**base)


# -- content_hash: determinism & portability --------------------------------


def test_content_hash_deterministic_same_input() -> None:
    a = _committed_fact()
    b = _committed_fact()
    assert content_hash(a) == content_hash(b)
    assert content_hash(a).startswith("sha256:")


def test_content_hash_independent_of_timestamps_and_actors() -> None:
    """Recording metadata must not affect the portable identity."""
    import datetime as _dt

    early = _committed_fact(
        created_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        updated_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
    )
    late = _committed_fact(
        created_at=_dt.datetime(2026, 5, 1, tzinfo=_dt.timezone.utc),
        updated_at=_dt.datetime(2026, 5, 1, tzinfo=_dt.timezone.utc),
    )
    assert content_hash(early) == content_hash(late)


def test_content_hash_independent_of_confidence_and_source_refs() -> None:
    """Confidence and source_refs are recording metadata, not portable identity."""
    from continuity.api.models import SourceRef

    plain = _committed_fact()
    annotated = _committed_fact(
        confidence=0.99,
        source_refs=[SourceRef(kind="url", ref="https://example.com/x")],
    )
    assert content_hash(plain) == content_hash(annotated)


def test_content_hash_changes_on_content_change() -> None:
    original = _committed_fact(content={"lesson": "v1"})
    rewritten = _committed_fact(content={"lesson": "v2 rewritten"})
    assert content_hash(original) != content_hash(rewritten)


def test_content_hash_changes_on_reliance_class_change() -> None:
    """Promoting reliance_class is a meaningful content change."""
    advisory = _committed_fact(reliance_class=RelianceClass.ADVISORY)
    actionable = _committed_fact(reliance_class=RelianceClass.ACTIONABLE)
    assert content_hash(advisory) != content_hash(actionable)


def test_content_hash_changes_on_supersedes_pointer() -> None:
    """Two versions in a chain differ by their supersedes pointer."""
    v1 = _committed_fact()
    v2 = _committed_fact(supersedes="mem_canonical_xyz_0000000000")
    assert content_hash(v1) != content_hash(v2)


# -- content_hash: status is OUT --------------------------------------------


def test_content_hash_does_not_change_on_revoke() -> None:
    """The whole point: revocation is state, not content."""
    committed = _committed_fact()
    revoked = _committed_fact(
        status=MemoryStatus.REVOKED,
        revoked_by="mem_replacement_0000000000000",
    )
    assert content_hash(committed) == content_hash(revoked)


# -- state_hash: posture changes ------------------------------------------


def test_state_hash_flips_on_revoke() -> None:
    committed = _committed_fact()
    revoked = _committed_fact(status=MemoryStatus.REVOKED)
    assert state_hash(committed) != state_hash(revoked)


def test_state_hash_flips_on_revoked_by_change() -> None:
    """Two revoked-by-different-replacements memories differ in state_hash."""
    revoked_by_a = _committed_fact(
        status=MemoryStatus.REVOKED, revoked_by="mem_replacement_aaaaaaaaaaa",
    )
    revoked_by_b = _committed_fact(
        status=MemoryStatus.REVOKED, revoked_by="mem_replacement_bbbbbbbbbbb",
    )
    assert state_hash(revoked_by_a) != state_hash(revoked_by_b)


def test_state_hash_includes_content_hash() -> None:
    """Content change reflects in state_hash too (it's a superset)."""
    a = _committed_fact(content={"lesson": "v1"})
    b = _committed_fact(content={"lesson": "v2"})
    assert state_hash(a) != state_hash(b)


def test_state_hash_matches_when_content_and_posture_match() -> None:
    a = _committed_fact()
    b = _committed_fact()
    assert state_hash(a) == state_hash(b)


# -- cross-store portability sketch ----------------------------------------


def test_content_hash_portable_across_simulated_stores() -> None:
    """Same source memory_id + same canonical content -> same hash anywhere.

    Simulating two stores holding the same imported memory at the same
    version. Local-only metadata (different created_at, source_refs
    annotations) is irrelevant; content_hash collapses on the portable
    payload.
    """
    import datetime as _dt
    from continuity.api.models import SourceRef

    store_a_copy = _committed_fact(
        created_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        source_refs=[SourceRef(kind="url", ref="https://store-a.example/x")],
    )
    store_b_copy = _committed_fact(
        created_at=_dt.datetime(2026, 4, 15, tzinfo=_dt.timezone.utc),
        confidence=0.42,
    )

    assert content_hash(store_a_copy) == content_hash(store_b_copy)


def test_distinct_source_memory_ids_yield_distinct_hashes() -> None:
    """Two different memories must hash differently even if other fields match."""
    a = _committed_fact(memory_id="mem_a_zzzzzzzzzzzzzzzzzzzzzz")
    b = _committed_fact(memory_id="mem_b_zzzzzzzzzzzzzzzzzzzzzz")
    assert content_hash(a) != content_hash(b)
