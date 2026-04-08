"""Test receipt hash chaining and content integrity."""

from continuity.api.models import (
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    ObserveMemoryRequest,
    RelianceClass,
)
from continuity.store.sqlite import SQLiteStore
from continuity.util.hashing import receipt_hash


def test_receipt_chain_integrity(store: SQLiteStore) -> None:
    """Verify that each receipt's hash is correctly derived from prev_hash + content."""
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="chain",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "hash chains are boring and good"},
    ))

    cmt = store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.RETRIEVE_ONLY,
    ))

    # Verify observe receipt hash
    expected_obs_hash = receipt_hash(
        receipt_type=str(obs.receipt.receipt_type),
        prev_hash=obs.receipt.prev_hash,
        content=obs.receipt.content,
    )
    assert obs.receipt.hash == expected_obs_hash

    # Verify commit receipt hash
    expected_cmt_hash = receipt_hash(
        receipt_type=str(cmt.receipt.receipt_type),
        prev_hash=cmt.receipt.prev_hash,
        content=cmt.receipt.content,
    )
    assert cmt.receipt.hash == expected_cmt_hash

    # Verify chain linkage
    assert cmt.receipt.prev_hash == obs.receipt.hash


def test_receipts_contain_premises(store: SQLiteStore) -> None:
    """Receipt content should include claimed premises at time of mutation."""
    from continuity.api.models import PremiseRef, SourceRef

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="receipt-premise",
        kind=MemoryKind.DECISION,
        basis=Basis.OPERATOR_ASSERTION,
        content={"decision": "use receipts"},
        premises=[
            PremiseRef(
                source_ref=SourceRef(ref="doc:architecture.md", kind="file"),
                relation="supports",
                note="architecture doc says so",
            ),
        ],
    ))

    assert "premises" in obs.receipt.content
    assert len(obs.receipt.content["premises"]) == 1
    assert obs.receipt.content["premises"][0]["note"] == "architecture doc says so"
