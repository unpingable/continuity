"""ArtifactObserver — read-only, emits one bounded claim per call.

Imports nothing from continuity (asserted by a test). It reads files and reports;
it never writes, never compares against a remembered claim, never decides skew.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from artifact_observer.models import (
    ArtifactObservation,
    ClaimKind,
    ObserverSourceRef,
    SubjectKind,
)

# Bound on what the observer will read into memory to make a claim. Larger or
# binary artifacts yield can_testify=False, honoring "bounded claims only."
_MAX_BYTES = 5 * 1024 * 1024
_CONTENT_CLAIMS = {ClaimKind.CONTAINS, ClaimKind.DECLARES, ClaimKind.OMITS}


def _boundary_now() -> datetime:
    """Resolve the scan time once, at the observe() boundary. Injectable for
    tests via the observed_at parameter — the same clock discipline continuity
    holds (no ambient read inside the claim logic)."""
    return datetime.now(timezone.utc)


def _git_head(repo_root: Path) -> str | None:
    """Best-effort current commit, read purely from files (no subprocess).
    Returns None if this is not a resolvable git worktree."""
    head = repo_root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if text.startswith("ref:"):
        ref = text.split(":", 1)[1].strip()
        ref_path = repo_root / ".git" / ref
        try:
            return ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return text or None


class ArtifactObserver:
    """Observe artifact state under a repo working tree. V0 handles file
    subjects and the four claim kinds (exists / contains / declares / omits)."""

    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.repo_name = self.repo_root.name

    def observe(
        self,
        subject: str,
        claim_kind: ClaimKind | str,
        *,
        needle: str | None = None,
        observed_at: datetime | None = None,
    ) -> ArtifactObservation:
        claim_kind = ClaimKind(claim_kind)
        at = observed_at or _boundary_now()
        commit = _git_head(self.repo_root)

        def _obs(**kw) -> ArtifactObservation:
            ref = ObserverSourceRef(
                repo=self.repo_name, path=subject,
                content_digest=kw.pop("digest", None),
                commit=commit, line=kw.pop("line", None),
            )
            return ArtifactObservation(
                subject=subject, subject_kind=SubjectKind.FILE,
                claim_kind=claim_kind, observed_at=at, source_ref=ref, **kw,
            )

        # Refuse subjects that escape the repo root — the observer testifies only
        # about the estate it was pointed at.
        target = (self.repo_root / subject).resolve()
        if not target.is_relative_to(self.repo_root):
            return _obs(can_testify=False,
                        cannot_testify_reason="subject path escapes the repo root")

        exists = target.is_file()

        if claim_kind == ClaimKind.EXISTS:
            digest = _sha256(target) if exists else None
            return _obs(claim_value="true" if exists else "false", digest=digest)

        # Content claims need a needle and readable text content.
        if claim_kind in _CONTENT_CLAIMS and not needle:
            return _obs(can_testify=False,
                        cannot_testify_reason=f"{claim_kind} requires a needle")
        if not exists:
            return _obs(can_testify=False,
                        cannot_testify_reason="subject does not exist; cannot observe content")

        try:
            size = target.stat().st_size
        except OSError as exc:
            return _obs(can_testify=False, cannot_testify_reason=f"unreadable: {exc}")
        if size > _MAX_BYTES:
            return _obs(can_testify=False,
                        cannot_testify_reason=f"artifact exceeds {_MAX_BYTES} bytes")

        raw = target.read_bytes()
        if b"\x00" in raw:
            return _obs(can_testify=False,
                        cannot_testify_reason="binary artifact; not a text observation")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _obs(can_testify=False,
                        cannot_testify_reason="artifact is not valid utf-8 text")

        digest = hashlib.sha256(raw).hexdigest()
        present = needle in text
        line = _first_line(text, needle) if present else None

        if claim_kind in (ClaimKind.CONTAINS, ClaimKind.DECLARES):
            return _obs(claim_value="true" if present else "false",
                        digest=digest, line=line)
        # OMITS: the claim "the artifact omits the needle" is true iff absent.
        return _obs(claim_value="true" if not present else "false", digest=digest)


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _first_line(text: str, needle: str) -> int | None:
    idx = text.find(needle)
    if idx < 0:
        return None
    return text.count("\n", 0, idx) + 1
