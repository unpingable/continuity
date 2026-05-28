"""Tests for the WLP persistence adapter.

Acceptance criteria from docs/MVP_A_SLICE_5_PACKET.md:

1. Adapter accepts WLP HandlingReceipt JSON byte-identical or
   canonical-byte-identical, per packet.
2. WLP-provided hash/custody preserved.
3. Readback through existing Continuity path.
4. sha256(canonical_readback_bytes) == wlp_provided_hash.
5. Invariants preserved (stored ≠ valid, retrieved ≠ trusted,
   indexed ≠ endorsed, persistence ≠ transport, receipt store ≠
   reliance engine).

Plus tests from docs/gaps/WLP_PERSISTENCE_ADAPTER_GAP.md:

- round-trip identity
- hash-match positive
- hash-match negative on tampered bytes
- idempotency (same envelope twice → same memory_id, single import receipt)
- explain() lineage surfaces causal_parents

Fixtures: tests/fixtures/ns_wlp_handling_sample.json and
ns_wlp_authorization_sample.json are byte-identical copies of the
MVP-A live-run artifacts produced by NS on 2026-05-28.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from continuity.adapters.wlp import (
    WLPHashMismatchError,
    WLPNonCanonicalInputError,
    readback_wlp_artifact,
    store_wlp_artifact,
    verify_wlp_artifact_hash,
    wlp_canonical_for_hash,
)
from continuity.store.sqlite import SQLiteStore

FIXTURE_DIR = Path(__file__).parent / "fixtures"
HANDLING_PATH = FIXTURE_DIR / "ns_wlp_handling_sample.json"
AUTHORIZATION_PATH = FIXTURE_DIR / "ns_wlp_authorization_sample.json"

# Hashes from the MVP-A run packet — these are the WLP-provided
# artifact_hash values inside the respective envelopes.
HANDLING_ARTIFACT_HASH = (
    "sha256:86126707b3974f5c160deabca6df9e968da17baab4c48cadaffb221b1ff47b19"
)
AUTHORIZATION_ARTIFACT_HASH = (
    "sha256:a6c341c4bd72f10a2d3482a86769c3345026675797fe104d063c04bf24daea7f"
)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    s = SQLiteStore(tmp_path / "store.db")
    s.initialize()
    return s


def _read(path: Path) -> bytes:
    return path.read_bytes()


# -- canonicalization sanity checks --------------------------------------

def test_handling_fixture_is_canonical() -> None:
    """The fixture as written by NS must survive JCS round-trip unchanged."""
    raw = _read(HANDLING_PATH)
    obj = json.loads(raw)
    re_canon = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert re_canon == raw


def test_wlp_canonical_for_hash_matches_provided() -> None:
    """Recomputing artifact_hash on the fixture yields the WLP-claimed hash."""
    raw = _read(HANDLING_PATH)
    envelope = json.loads(raw)
    canon = wlp_canonical_for_hash(envelope)
    digest = "sha256:" + hashlib.sha256(canon).hexdigest()
    assert digest == HANDLING_ARTIFACT_HASH


# -- store path ----------------------------------------------------------

def test_store_handling_artifact_returns_identifiers(store: SQLiteStore) -> None:
    raw = _read(HANDLING_PATH)
    result = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
        scope="wlp",
        source_store_id="ns:nightshiftd",
        source_path=str(HANDLING_PATH),
    )
    assert result.wlp_artifact_hash == HANDLING_ARTIFACT_HASH
    assert result.wlp_kind == "HandlingReceipt"
    assert result.memory_id.startswith("mem_wlp_")
    assert result.receipt_id.startswith("rcpt_")
    assert result.already_imported is False
    # causal_parents preserved from envelope.custody.causal_parents
    assert result.causal_parents == [
        "sha256:a6c341c4bd72f10a2d3482a86769c3345026675797fe104d063c04bf24daea7f"
    ]


def test_non_canonical_input_refused(store: SQLiteStore) -> None:
    """Adapter does not silently re-canonicalize input (invariant 1)."""
    raw = _read(HANDLING_PATH)
    # Pretty-print, breaking canonical form
    obj = json.loads(raw)
    non_canonical = json.dumps(obj, indent=2).encode("utf-8")
    with pytest.raises(WLPNonCanonicalInputError):
        store_wlp_artifact(
            store,
            envelope_bytes=non_canonical,
            wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
        )


# -- readback path -------------------------------------------------------

def test_readback_yields_byte_identical_canonical(store: SQLiteStore) -> None:
    """Acceptance #3: read back through existing Continuity path returns
    byte-identical canonical JSON."""
    raw = _read(HANDLING_PATH)
    result = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
    )
    readback = readback_wlp_artifact(store, result.memory_id)
    assert readback == raw


def test_readback_via_get_memory_directly(store: SQLiteStore) -> None:
    """Explicitly walk the existing get_memory path; envelope dict survives."""
    raw = _read(HANDLING_PATH)
    result = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
    )
    memory = store.get_memory(result.memory_id)
    re_canon = json.dumps(memory.content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert re_canon == raw


# -- hash verification ---------------------------------------------------

def test_verify_hash_positive_after_store_readback(store: SQLiteStore) -> None:
    """Acceptance #4: sha256(canonical_readback) == wlp_provided_hash."""
    raw = _read(HANDLING_PATH)
    result = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
    )
    readback = readback_wlp_artifact(store, result.memory_id)
    assert verify_wlp_artifact_hash(readback, HANDLING_ARTIFACT_HASH) is True


def test_verify_hash_negative_on_tampered_bytes() -> None:
    """Tamper detection: changed bytes do not hash to provided artifact_hash."""
    raw = _read(HANDLING_PATH)
    envelope = json.loads(raw)
    # Tamper a non-hash field (e.g., flip `acted` from true to false).
    envelope["acted"] = not envelope["acted"]
    tampered = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert verify_wlp_artifact_hash(tampered, HANDLING_ARTIFACT_HASH) is False


def test_verify_hash_negative_on_garbage_bytes() -> None:
    assert verify_wlp_artifact_hash(b"not json at all", HANDLING_ARTIFACT_HASH) is False


# -- idempotency ---------------------------------------------------------

def test_store_idempotent_for_same_envelope(store: SQLiteStore) -> None:
    """Two stores of the same envelope yield one memory_id and a single
    import event/receipt (per ImportMemoryRequest's (memory_id,
    content_hash) check)."""
    raw = _read(HANDLING_PATH)
    first = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
    )
    second = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
    )
    assert first.memory_id == second.memory_id
    assert first.receipt_id == second.receipt_id
    assert second.already_imported is True


# -- explain() / lineage -------------------------------------------------

def test_explain_surfaces_wlp_artifact_hash_in_receipt(store: SQLiteStore) -> None:
    """Acceptance #5: lineage walks the WLP custody/import receipt.

    The import receipt's content carries source_ref = wlp_artifact_hash;
    the envelope content (memory.content) carries custody.causal_parents
    unchanged."""
    raw = _read(HANDLING_PATH)
    result = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=HANDLING_ARTIFACT_HASH,
        source_store_id="ns:nightshiftd",
    )
    e = store.explain_memory(result.memory_id)

    # Import receipt records the WLP artifact_hash as source_ref.
    import_receipts = [r for r in e.receipts if str(r.receipt_type) == "memory.import"]
    assert import_receipts, "expected at least one memory.import receipt"
    rcpt = import_receipts[0]
    assert rcpt.content.get("source_ref") == HANDLING_ARTIFACT_HASH
    assert rcpt.content.get("source_store_id") == "ns:nightshiftd"

    # Envelope's custody.causal_parents survives in the memory's content.
    assert e.memory.content["custody"]["causal_parents"] == [
        "sha256:a6c341c4bd72f10a2d3482a86769c3345026675797fe104d063c04bf24daea7f"
    ]


# -- authorization receipt round-trip ------------------------------------

def test_authorization_receipt_round_trip(store: SQLiteStore) -> None:
    """The MVP-A AuthorizationReceipt also persists with hash match."""
    raw = _read(AUTHORIZATION_PATH)
    result = store_wlp_artifact(
        store,
        envelope_bytes=raw,
        wlp_artifact_hash=AUTHORIZATION_ARTIFACT_HASH,
    )
    assert result.wlp_kind == "AuthorizationReceipt"
    readback = readback_wlp_artifact(store, result.memory_id)
    assert readback == raw
    assert verify_wlp_artifact_hash(readback, AUTHORIZATION_ARTIFACT_HASH) is True


# -- invariant-shape refusals --------------------------------------------

def test_adapter_does_not_validate_wlp_semantics(store: SQLiteStore) -> None:
    """Invariant 8: WLP-valid envelope ≠ authorized action.

    The adapter signature carries no 'is_valid?' parameter and exposes
    no policy decision point. This test asserts the surface by
    structural inspection: the store_wlp_artifact function does not
    return a verdict, and the return type carries no 'valid' / 'authorized'
    / 'trusted' field.
    """
    from continuity.adapters.wlp import WLPArtifactStored
    fields = {f.name for f in WLPArtifactStored.__dataclass_fields__.values()}
    assert "valid" not in fields
    assert "authorized" not in fields
    assert "trusted" not in fields
    assert "verdict" not in fields


def test_adapter_module_exposes_no_transport_surface() -> None:
    """Invariant 11: persistence ≠ transport.

    The adapter module's __all__ does not expose subscribe / notify /
    deliver / publish / announce / replay primitives."""
    from continuity.adapters import wlp as adapter
    forbidden = {
        "subscribe", "notify", "deliver", "publish", "announce", "replay",
        "propagate", "broadcast", "fanout",
    }
    exposed = set(adapter.__all__)
    assert exposed.isdisjoint(forbidden), (
        f"transport-shaped names leaked into adapter __all__: "
        f"{exposed & forbidden}"
    )
