"""Declaration export contract: quote statuses, never assert authority.

`continuity.declaration_export.v0` is the surface a consumer (e.g. the Spine read
plane) locates and packages. It must be deliberately humiliating: deterministic,
versioned, digest-over-declarations, statuses emitted as *quoted source statuses*,
and carrying no authority/recency field. These tests pin all of that.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from continuity.api.models import MemoryObject
from continuity.cli import main
from continuity.declaration_export import (
    FORBIDDEN_EXPORT_FIELDS,
    SCHEMA,
    SOURCE_STANDING,
    DeclarationEntry,
    DeclarationExport,
    ExportError,
    ExportSource,
    SourceStatus,
    _all_keys_lower,
    _assert_no_forbidden_fields,
    build_declaration_export,
)

_EXPORTED_AT = "2026-06-28T00:00:00.000000+00:00"
_SOURCE = ExportSource(version="0.1.0-test")


def _mem(
    ref,
    *,
    path=None,
    status="committed",
    reliance="advisory",
    kind="decision",
    scope="spine",
    supersedes=None,
    confidence=0.8,
):
    content = {"ref": ref}
    if path is not None:
        content["path"] = path
    return MemoryObject(
        scope=scope,
        kind=kind,
        basis="operator_assertion",
        status=status,
        reliance_class=reliance,
        confidence=confidence,
        content=content,
        supersedes=supersedes,
    )


def _build(memories, exported_at=_EXPORTED_AT):
    return build_declaration_export(memories, exported_at=exported_at, source=_SOURCE)


# --- schema / shape ---------------------------------------------------------- #


def test_export_is_versioned_with_the_schema_tag():
    export, _ = _build([_mem("spine:DOCTRINE.md", path="DOCTRINE.md")])
    wire = export.canonical_dict()
    assert wire["schema"] == SCHEMA == "continuity.declaration_export.v0"
    assert wire["export_id"].startswith("sha256:")
    assert len(wire["declarations"]) == 1
    assert wire["declarations"][0]["ref"] == "spine:DOCTRINE.md"
    assert wire["declarations"][0]["path"] == "DOCTRINE.md"


# --- determinism + digest covers declarations -------------------------------- #


def test_export_is_deterministic_for_the_same_memories():
    mems = [_mem("spine:DOCTRINE.md"), _mem("agent_gov:docs/x.md", scope="agent_gov")]
    a, _ = _build(mems)
    b, _ = _build(mems)
    assert a.canonical_dict() == b.canonical_dict()
    assert a.export_id == b.export_id


def test_export_id_excludes_exported_at():
    """The digest is content-addressed: same declarations exported at different times
    share an export_id. exported_at is provenance, not content."""
    mems = [_mem("spine:DOCTRINE.md")]
    a, _ = _build(mems, exported_at="2026-06-28T00:00:00.000000+00:00")
    b, _ = _build(mems, exported_at="2026-07-01T09:09:09.000000+00:00")
    assert a.exported_at != b.exported_at
    assert a.export_id == b.export_id


def test_export_id_covers_the_declarations():
    a, _ = _build([_mem("spine:DOCTRINE.md")])
    b, _ = _build([_mem("spine:OTHER.md")])
    assert a.export_id != b.export_id


def test_declarations_are_sorted_for_determinism():
    export, _ = _build([_mem("spine:z.md"), _mem("spine:a.md"), _mem("spine:m.md")])
    refs = [d.ref for d in export.declarations]
    assert refs == ["spine:a.md", "spine:m.md", "spine:z.md"]


# --- statuses are QUOTED source statuses, not universal facts ---------------- #


def test_status_is_emitted_as_a_quoted_source_status():
    export, _ = _build([_mem("spine:DOCTRINE.md", status="committed")])
    d = export.declarations[0]
    assert d.source_status.value == "committed"          # the raw status, quoted
    assert d.source_status.standing == SOURCE_STANDING   # ...visibly not standing
    assert d.source_status.standing == "quoted_continuity_status_not_spine_standing"


def test_even_actionable_reliance_is_only_quoted_metadata():
    export, _ = _build([_mem("spine:DOCTRINE.md", reliance="actionable")])
    meta = export.declarations[0].source_metadata
    assert meta["reliance_class"] == "actionable"  # quoted, descriptive
    # ...and it appears nowhere as a standing/authority claim.
    assert export.declarations[0].source_status.standing == SOURCE_STANDING


def test_supersedes_is_quoted_metadata_not_supersession_as_truth():
    export, _ = _build([_mem("spine:DOCTRINE.md", supersedes="mem_oldoldold")])
    meta = export.declarations[0].source_metadata
    assert meta["supersedes"] == "mem_oldoldold"  # the pointer, quoted
    # the *claim* of supersession-as-truth must not exist anywhere.
    assert "supersedes_as_truth" not in set(_all_keys_lower(export.canonical_dict()))


# --- no authority/recency field anywhere ------------------------------------- #


def test_export_carries_no_forbidden_authority_field():
    export, _ = _build([
        _mem("spine:DOCTRINE.md", reliance="actionable", supersedes="mem_oldoldold"),
        _mem("agent_gov:docs/x.md", scope="agent_gov", status="observed"),
    ])
    keys = set(_all_keys_lower(export.canonical_dict()))
    assert not (keys & FORBIDDEN_EXPORT_FIELDS)


def test_authority_key_in_content_does_not_leak_into_the_export():
    """source_metadata is an allowlist, so a memory cannot smuggle an authority field
    through its free-form content."""
    mem = MemoryObject(
        scope="spine", kind="decision", basis="operator_assertion", status="committed",
        reliance_class="advisory",
        content={"ref": "spine:DOCTRINE.md", "canonical": True, "ratified": "yes"},
    )
    export, _ = _build([mem])
    keys = set(_all_keys_lower(export.canonical_dict()))
    assert "canonical" not in keys
    assert "ratified" not in keys
    # the ref still made it through — declaring is fine, conferring is not.
    assert export.declarations[0].ref == "spine:DOCTRINE.md"


def test_self_check_refuses_a_forbidden_field_with_teeth():
    """If a forbidden field ever reached the serialized export, the builder refuses
    rather than emit it."""
    bad = DeclarationExport(
        export_id="sha256:" + "0" * 64,
        exported_at=_EXPORTED_AT,
        source=_SOURCE,
        declarations=[
            DeclarationEntry(
                ref="spine:DOCTRINE.md",
                source_status=SourceStatus(value="committed"),
                source_metadata={"canonical": "smuggled"},
            )
        ],
    )
    with pytest.raises(ExportError):
        _assert_no_forbidden_fields(bad)


# --- no silent drops --------------------------------------------------------- #


def test_memory_without_a_ref_is_excluded_with_a_reason():
    mem = MemoryObject(
        scope="spine", kind="note", basis="inference",
        content={"text": "a memory that declares no artifact"},
    )
    export, excluded = _build([mem])
    assert export.declarations == []  # nothing declared...
    assert len(excluded) == 1         # ...but it is accounted for, not dropped
    assert excluded[0].memory_id == mem.memory_id
    assert excluded[0].reason == "no_locatable_ref"


# --- CLI integration: contctl export ----------------------------------------- #


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


def _run(db_path: str, argv: list[str]) -> str:
    import io

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        main(["--db", db_path] + argv)
    return buf.getvalue()


def test_cli_export_emits_a_declaration_export(db_path: str):
    _run(db_path, ["init"])
    observed = json.loads(_run(db_path, [
        "observe", "--scope", "spine", "--kind", "decision",
        "--basis", "operator_assertion",
        "--content", '{"ref": "spine:DOCTRINE.md", "path": "DOCTRINE.md"}',
    ]))
    _run(db_path, ["commit", observed["memory_id"], "--reliance-class", "advisory"])

    export = json.loads(_run(db_path, ["export", "--scope", "spine"]))
    assert export["schema"] == "continuity.declaration_export.v0"
    assert export["export_id"].startswith("sha256:")
    assert len(export["declarations"]) == 1
    d = export["declarations"][0]
    assert d["ref"] == "spine:DOCTRINE.md"
    assert d["path"] == "DOCTRINE.md"
    assert d["source_status"]["value"] == "committed"
    assert d["source_status"]["standing"] == "quoted_continuity_status_not_spine_standing"
    assert export["source"]["tool"] == "continuity"
