"""Golden conformance fixture for `continuity.declaration_export.v0`.

ROADMAP slice 2 (Spine 2c support). The existing `test_declaration_export.py`
pins the export's *structure*; this file freezes a full document to *bytes* in
`tests/fixtures/declaration_export_v0_golden.json`.

That golden file is the artifact Spine vendors for Slice 2c — the same way
Spine's 2b fixture (`continuity_export_shape_v0.json`) was vendored, but shaped
to the *real* contract this repo ships rather than the pre-export
`continuity.receipt.v0` envelope list 2b assumed. See the "Consumer
reconciliation" section of `docs/DECLARATION_EXPORT_V0.md`.

Two things are locked here:

1. **Byte stability** — the builder reproduces the golden exactly from a fixed
   corpus + fixed `exported_at` + fixed `source`. If this fails, the wire format
   changed; regenerate the golden *and* tell Spine, because a vendored copy just
   drifted.
2. **The `ref` convention Spine maps on** — every `ref` is `"<repo>:<path>"`,
   and splitting on the first `:` recovers a repo prefix plus the declaration's
   own `path`. This is the seam 2c uses to fill Spine's `ManifestArtifact`
   (repo, path); freezing it means 2c is coding against a guarantee, not an
   accident of the sample.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from continuity.api.models import MemoryObject
from continuity.declaration_export import ExportSource, build_declaration_export

_GOLDEN = Path(__file__).parent / "fixtures" / "declaration_export_v0_golden.json"

# Pinned so the fixture is byte-stable. exported_at and source.version are the
# only non-content inputs; created_at is pinned per-memory because declared_at
# quotes it (and declared_at is inside the digest).
_EXPORTED_AT = "2026-07-03T00:00:00.000000+00:00"
_SOURCE = ExportSource(version="0.1.0")


def _ts(day: int, hour: int) -> datetime:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=timezone.utc)


def _mem(ref, path, *, scope, kind, reliance, created_at, supersedes=None):
    return MemoryObject(
        scope=scope,
        kind=kind,
        basis="operator_assertion",
        status="committed",
        reliance_class=reliance,
        confidence=0.8,
        content={"ref": ref, "path": path},
        supersedes=supersedes,
        created_at=created_at,
    )


def _corpus() -> list[MemoryObject]:
    """The frozen Spine-shaped corpus behind the golden fixture.

    Keep this in lockstep with the golden file: change one, regenerate the
    other, and flag Spine. A note carries retrieve_only; NAMING carries a
    quoted supersedes pointer; agent_gov uses a different repo prefix — so the
    fixture exercises metadata variety and the multi-repo split, not just the
    happy path.
    """
    return [
        _mem("spine:DOCTRINE.md", "DOCTRINE.md", scope="spine",
             kind="decision", reliance="advisory", created_at=_ts(10, 9)),
        _mem("spine:README.md", "README.md", scope="spine",
             kind="note", reliance="retrieve_only", created_at=_ts(10, 10)),
        _mem("spine:NAMING.md", "NAMING.md", scope="spine",
             kind="decision", reliance="advisory",
             supersedes="mem_prior_naming_note0", created_at=_ts(12, 14)),
        _mem("agent_gov:docs/roadmaps/README.md", "docs/roadmaps/README.md",
             scope="agent_gov", kind="decision", reliance="advisory",
             created_at=_ts(11, 16)),
    ]


def _build_wire() -> dict:
    export, excluded = build_declaration_export(
        _corpus(), exported_at=_EXPORTED_AT, source=_SOURCE,
    )
    assert excluded == []  # the corpus is all locatable declarations
    return export.canonical_dict()


def test_builder_reproduces_the_golden_fixture_byte_for_byte():
    wire = _build_wire()
    rendered = json.dumps(wire, indent=2, ensure_ascii=False) + "\n"
    golden = _GOLDEN.read_text(encoding="utf-8")
    assert rendered == golden, (
        "declaration_export.v0 wire form drifted from the vendored golden. "
        "If intentional, regenerate tests/fixtures/declaration_export_v0_golden.json "
        "and notify Spine — a vendored copy just went stale."
    )


def test_golden_is_a_valid_v0_document():
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert golden["schema"] == "continuity.declaration_export.v0"
    assert golden["export_id"].startswith("sha256:")
    assert golden["source"]["tool"] == "continuity"
    assert len(golden["declarations"]) == 4
    for d in golden["declarations"]:
        # every status is a QUOTED continuity status, never Spine standing
        assert d["source_status"]["standing"] == "quoted_continuity_status_not_spine_standing"


def test_ref_splits_into_repo_and_path_for_the_consumer():
    """The seam Spine 2c maps on: ref = '<repo>:<path>', split on first ':'.

    Frozen so 2c can fill ManifestArtifact(repo, path) from the export without
    guessing. The recovered path must equal the declaration's own `path`.
    """
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    for d in golden["declarations"]:
        assert ":" in d["ref"]
        repo, _, ref_path = d["ref"].partition(":")
        assert repo  # non-empty repo prefix
        assert ref_path == d["path"]
    # and the corpus spans more than one repo, so the split is load-bearing
    repos = {d["ref"].partition(":")[0] for d in golden["declarations"]}
    assert repos == {"spine", "agent_gov"}
