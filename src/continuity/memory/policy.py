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
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryObject,
    ObserveMemoryRequest,
    RelianceClass,
    RepairMemoryRequest,
)


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

    def allow_observe(self, req: ObserveMemoryRequest) -> PolicyResult:
        return PolicyResult(Decision.ALLOW, "observe allowed by default")

    def allow_commit(self, req: CommitMemoryRequest) -> PolicyResult:
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
