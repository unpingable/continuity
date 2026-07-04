"""Artifact Observer — the light source for MapSkew.

A read-only surface that emits bounded artifact-state claims: *here is what the
artifact currently says.* It is a DIFFERENT organ from continuity — it observes
reality, it does not remember it, and it never imports the continuity store,
mutates memory, compares against a remembered claim, or decides skew. Those are
MapSkew's job, in a later gap.

See docs/gaps/MAPSKEW_OBSERVATION_SIDE_V0.md. Colocated in this repo as a V0
specimen; it moves to its own repo if it grows past a specimen.
"""

from artifact_observer.models import (
    ArtifactObservation,
    ClaimKind,
    ObserverSourceRef,
    SubjectKind,
)
from artifact_observer.observer import ArtifactObserver

__all__ = [
    "ArtifactObservation",
    "ClaimKind",
    "ObserverSourceRef",
    "SubjectKind",
    "ArtifactObserver",
]

__version__ = "0.0.1"
