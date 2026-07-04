"""Memory policy — the seam where Governor will eventually live.

Default rules for slice 0:
  - observe: allowed locally
  - commit: allowed only via operator or trusted standing
  - inference cannot become actionable without explicit promotion
  - expired or revoked memory cannot be relied on
  - summary and hypothesis default to retrieve_only
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from continuity.api.models import (
    AuthoringTier,
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryObject,
    ObserveMemoryRequest,
    RelianceClass,
    RepairMemoryRequest,
    reliance_exceeds,
    tier_cap,
)

# Tiers a routine observe/commit may declare. custodian_signed requires a
# custody event (adjudicate); revoked is a derived standing-loss state;
# provenance_unknown is a backfill/import label. None of the three is
# self-declarable via a normal write — that is the core anti-laundering gate.
_SELF_DECLARABLE_TIERS = frozenset({
    AuthoringTier.AGENT_AUTHORED,
    AuthoringTier.RUNTIME_AUTHORED,
})


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == Decision.ALLOW


class MemoryPolicy:
    """Default memory policy. Override for Governor integration."""

    def tier_cap(self, tier: AuthoringTier | str) -> RelianceClass:
        """The maximum reliance_class an entry of this authoring tier may be
        relied on at. The anti-laundering ceiling — see MEMORY_AUTHORING_TIER."""
        return tier_cap(tier)

    def allow_write_tier(self, tier: AuthoringTier | str | None) -> PolicyResult:
        """Gate a write-time authoring tier. None is allowed (resolves to the
        agent_authored default at the boundary). custodian_signed / revoked /
        provenance_unknown are refused: a routine write cannot self-declare
        custody, standing loss, or unknown provenance."""
        if tier is None:
            return PolicyResult(Decision.ALLOW, "authoring tier defaults to agent_authored")
        if AuthoringTier(tier) in _SELF_DECLARABLE_TIERS:
            return PolicyResult(Decision.ALLOW, f"authoring tier {tier} is self-declarable")
        return PolicyResult(
            Decision.DENY,
            f"authoring_tier={tier} is not self-declarable via a routine write "
            "(custodian_signed requires a custody event; revoked and "
            "provenance_unknown are derived/backfill labels)",
        )

    def allow_reliance_for_tier(
        self, tier: AuthoringTier | str, requested_class: RelianceClass | str,
    ) -> PolicyResult:
        """Refuse a commit whose reliance_class exceeds the tier's cap. This is
        the write-time half of the cap; rely re-applies it (effective_reliance)."""
        cap = tier_cap(tier)
        if reliance_exceeds(requested_class, cap):
            return PolicyResult(
                Decision.DENY,
                f"reliance_class={requested_class} exceeds the cap for "
                f"authoring_tier={tier} (max {cap})",
            )
        return PolicyResult(
            Decision.ALLOW,
            f"reliance_class={requested_class} within cap {cap} for tier {tier}",
        )

    def allow_observe(self, req: ObserveMemoryRequest) -> PolicyResult:
        tier_decision = self.allow_write_tier(req.authoring_tier)
        if not tier_decision.allowed:
            return tier_decision
        return PolicyResult(Decision.ALLOW, "observe allowed by default")

    def allow_commit(self, req: CommitMemoryRequest) -> PolicyResult:
        # A commit may restate the authoring tier; if it does, it faces the same
        # self-declarable gate as observe. The reliance-vs-cap check needs the
        # resolved tier (request-or-object) and runs in the store.
        tier_decision = self.allow_write_tier(req.authoring_tier)
        if not tier_decision.allowed:
            return tier_decision
        # ACTIONABLE requires explicit operator approval — the approved_by
        # field is how operator approval is signaled. The rely-time check
        # in _compute_rely_state additionally bars actionable+inference and
        # actionable+summary regardless of approval, so this gate is the
        # write-time half of the same restriction (matched semantics:
        # the operator's approval gets recorded as part of the request).
        if (
            req.reliance_class == RelianceClass.ACTIONABLE
            and req.approved_by is None
        ):
            return PolicyResult(
                Decision.DENY,
                "actionable reliance requires explicit operator approval",
            )
        return PolicyResult(Decision.ALLOW, "commit allowed by default")

    def allow_repair(self, req: RepairMemoryRequest) -> PolicyResult:
        # Repair is metadata-and-content only — semantic restrictions are
        # enforced at the model layer via RepairMemoryRequest.ALLOWED_PATCH_KEYS.
        # Policy can still deny (e.g., for actor standing), but defaults allow.
        return PolicyResult(Decision.ALLOW, "repair allowed by default")

    def allow_rely(
        self,
        memory: MemoryObject,
        context: dict[str, Any] | None = None,
    ) -> PolicyResult:
        if memory.status == "revoked":
            return PolicyResult(Decision.DENY, "memory is revoked")

        if memory.status != "committed":
            return PolicyResult(
                Decision.DENY,
                f"memory status is {memory.status}, not committed",
            )

        if memory.reliance_class == RelianceClass.NONE:
            return PolicyResult(Decision.DENY, "reliance_class=none")

        if (
            memory.kind in {MemoryKind.SUMMARY, MemoryKind.HYPOTHESIS}
            and memory.reliance_class == RelianceClass.ACTIONABLE
        ):
            return PolicyResult(
                Decision.DENY,
                f"{memory.kind} cannot be actionable without explicit promotion",
            )

        if (
            memory.basis in {Basis.INFERENCE, Basis.SYNTHESIS}
            and memory.reliance_class == RelianceClass.ACTIONABLE
        ):
            return PolicyResult(
                Decision.DENY,
                f"basis={memory.basis} cannot be actionable without explicit promotion",
            )

        return PolicyResult(
            Decision.ALLOW,
            f"reliance allowed at class {memory.reliance_class}",
        )
