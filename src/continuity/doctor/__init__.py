"""Continuity doctor — audit checks over memory artifacts.

Doctor checks emit testimony (findings), never authority. Per the
self-subject-collapse discipline in docs/gaps/PREMISE_CONSISTENCY_DOCTOR.md,
no check in this module writes to the memory store, mutates memory
records, or resolves the findings it raises.
"""

from continuity.doctor.authoring_tier import (
    TierFinding,
    TierFindingStatus,
    check_authoring_tier,
)
from continuity.doctor.premise_consistency import (
    Finding,
    FindingStatus,
    check_premise_consistency,
)

__all__ = [
    "Finding",
    "FindingStatus",
    "check_premise_consistency",
    "TierFinding",
    "TierFindingStatus",
    "check_authoring_tier",
]
