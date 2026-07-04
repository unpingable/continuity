"""Doctor check: authoring-tier violations.

V1 of MEMORY_AUTHORING_TIER_GAP §8. Testimony, never authority — like every
doctor check, this reads the store and reports; it writes nothing and resolves
nothing (self-subject-collapse discipline).

Two violation classes in V1:

1. **cap_exceeded** — a committed memory whose stored `reliance_class` exceeds
   its authoring tier's cap. Legacy rows (backfilled `provenance_unknown`, cap
   `retrieve_only`) committed at a higher class land here, as do rows whose tier
   was later tightened. The row is not wrong to *hold* that class — rely already
   returns the capped value — but the gap surfaces the discrepancy so an operator
   can adjudicate or re-commit.

2. **revoked_tier_cited** — a memory at `authoring_tier=revoked` (author standing
   ended) still cited as an active premise by a live dependent. History stays
   walkable, but a live claim leaning on a revoked-standing premise deserves a
   flag.

`standing_contested` surfacing (also named in §8) is deferred with the rest of
the standing-loss machinery — V1 has no producer for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from continuity.api.models import (
    MemoryStatus,
    RelianceClass,
    reliance_exceeds,
    tier_cap,
)


class TierFindingStatus(str, Enum):
    OK = "OK"
    FLAG = "FLAG"


@dataclass
class TierFinding:
    status: TierFindingStatus
    memory_id: str
    scope: str
    kind: str
    reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status.value,
            "memory_id": self.memory_id,
            "scope": self.scope,
            "kind": self.kind,
        }
        if self.reason is not None:
            d["reason"] = self.reason
        if self.evidence:
            d["evidence"] = self.evidence
        return d


def check_authoring_tier(store) -> list[TierFinding]:
    """Scan the store for authoring-tier violations. Returns findings, most
    actionable first; an OK finding is emitted only when the store is clean so
    the caller can report "N checked, 0 flagged" honestly."""
    findings: list[TierFinding] = []
    memories = store.list_all_memories()

    for m in memories:
        # 1. cap_exceeded — committed rows whose stored class is above the cap.
        if m.status == MemoryStatus.COMMITTED:
            cap = tier_cap(m.authoring_tier)
            if reliance_exceeds(m.reliance_class, cap):
                findings.append(TierFinding(
                    status=TierFindingStatus.FLAG,
                    memory_id=m.memory_id,
                    scope=m.scope,
                    kind=str(m.kind),
                    reason=(
                        f"stored reliance_class={m.reliance_class} exceeds the cap "
                        f"{cap} for authoring_tier={m.authoring_tier}; rely returns "
                        f"the capped value (effective={cap})"
                    ),
                    evidence={
                        "authoring_tier": str(m.authoring_tier),
                        "stored_reliance_class": str(m.reliance_class),
                        "tier_cap": str(cap),
                    },
                ))

        # 2. revoked_tier_cited — revoked-standing premise still cited live.
        if str(m.authoring_tier) == "revoked":
            dependents = store.active_dependents(m.memory_id)
            live = [
                link for link in dependents
                if link.dst_memory_id is not None
            ]
            if live:
                findings.append(TierFinding(
                    status=TierFindingStatus.FLAG,
                    memory_id=m.memory_id,
                    scope=m.scope,
                    kind=str(m.kind),
                    reason=(
                        "authoring_tier=revoked (author standing ended) but still "
                        f"cited as an active premise by {len(live)} dependent(s)"
                    ),
                    evidence={
                        "dependent_ids": [
                            link.dst_memory_id for link in live
                        ],
                    },
                ))

    if not findings:
        findings.append(TierFinding(
            status=TierFindingStatus.OK,
            memory_id="-",
            scope="-",
            kind="-",
            reason=f"{len(memories)} memories checked, no tier violations",
        ))
    return findings
