"""Artifact Observer V0 — the light source for MapSkew.

Pins the boundary: read-only, its own claim shape, zero continuity coupling,
`can_testify=False` as a first-class outcome distinct from observed absence, and
a reproducible digest. Includes a dogfood fixture that observes continuity's own
repo — a real artifact-state claim, the second input MapSkew was missing.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from artifact_observer import ArtifactObserver, ClaimKind, SubjectKind

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "present.txt").write_text("alpha\nbeta GAMMA delta\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02machine")
    return tmp_path


def _at() -> datetime:
    return datetime(2026, 7, 4, 0, 0, 0, tzinfo=timezone.utc)


# --- exists ----------------------------------------------------------------- #


def test_exists_true_with_digest(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe("present.txt", ClaimKind.EXISTS, observed_at=_at())
    assert o.can_testify is True
    assert o.claim_value == "true"
    assert o.subject_kind == SubjectKind.FILE
    assert o.observed_at == _at()
    assert o.source_ref.content_digest is not None  # reproducible line-of-sight


def test_exists_false_is_testimony_not_refusal(sandbox: Path) -> None:
    """Observed absence is a claim (exists=false), NOT can_testify=false."""
    o = ArtifactObserver(sandbox).observe("missing.txt", ClaimKind.EXISTS, observed_at=_at())
    assert o.can_testify is True
    assert o.claim_value == "false"
    assert o.source_ref.content_digest is None


# --- contains / declares / omits -------------------------------------------- #


def test_contains_true_records_line(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe(
        "present.txt", ClaimKind.CONTAINS, needle="GAMMA", observed_at=_at())
    assert o.claim_value == "true"
    assert o.source_ref.line == 2


def test_contains_false_when_absent(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe(
        "present.txt", ClaimKind.CONTAINS, needle="OMEGA", observed_at=_at())
    assert o.claim_value == "false"
    assert o.source_ref.line is None


def test_omits_is_inverse_of_contains(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe(
        "present.txt", ClaimKind.OMITS, needle="OMEGA", observed_at=_at())
    assert o.claim_value == "true"  # it does omit OMEGA


def test_content_claim_needs_needle(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe("present.txt", ClaimKind.CONTAINS, observed_at=_at())
    assert o.can_testify is False
    assert "needle" in o.cannot_testify_reason


# --- cannot_testify --------------------------------------------------------- #


def test_content_claim_on_missing_file_cannot_testify(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe(
        "missing.txt", ClaimKind.CONTAINS, needle="x", observed_at=_at())
    assert o.can_testify is False
    assert "does not exist" in o.cannot_testify_reason


def test_binary_artifact_cannot_testify(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe(
        "binary.bin", ClaimKind.CONTAINS, needle="machine", observed_at=_at())
    assert o.can_testify is False
    assert "binary" in o.cannot_testify_reason


def test_path_escaping_repo_root_cannot_testify(sandbox: Path) -> None:
    o = ArtifactObserver(sandbox).observe(
        "../../etc/passwd", ClaimKind.EXISTS, observed_at=_at())
    assert o.can_testify is False
    assert "escapes" in o.cannot_testify_reason


# --- the boundary: no continuity coupling ----------------------------------- #


def test_observer_does_not_import_continuity() -> None:
    """The observation organ is NOT continuity — it must not reach into the
    memory substrate. Guards the self-licking-map boundary by AST: no import of
    any continuity module anywhere in the package."""
    import ast

    pkg = REPO_ROOT / "src" / "artifact_observer"
    for src_file in pkg.glob("*.py"):
        tree = ast.parse(src_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("continuity"), src_file.name
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("continuity"), src_file.name


# --- dogfood: observe continuity's own repo --------------------------------- #


def test_dogfood_observe_continuity_repo() -> None:
    """A real artifact-state claim about this very repo — the second input
    MapSkew was missing. The observer testifies that the declaration-export
    module currently contains its schema tag."""
    observer = ArtifactObserver(REPO_ROOT)
    o = observer.observe(
        "src/continuity/declaration_export.py",
        ClaimKind.CONTAINS,
        needle="continuity.declaration_export.v0",
        observed_at=_at(),
    )
    assert o.can_testify is True
    assert o.claim_value == "true"
    assert o.source_ref.repo == "continuity"
    assert o.source_ref.content_digest is not None
    # digest is reproducible: a second scan of the unchanged file matches.
    again = observer.observe(
        "src/continuity/declaration_export.py", ClaimKind.EXISTS, observed_at=_at())
    assert again.source_ref.content_digest == o.source_ref.content_digest
