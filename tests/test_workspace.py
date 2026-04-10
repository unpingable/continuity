"""Tests for workspaces: named cross-project stores."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from continuity.util import dbpath
from continuity.util.dbpath import (
    list_workspaces,
    resolve_db_path,
    source_to_scope_kind,
    workspace_db_path,
    workspace_dir,
    workspace_manifest_path,
)
from continuity import workspace as ws_mod


@pytest.fixture
def workspaces_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect WORKSPACES_DIR into tmp_path so tests don't touch real config."""
    root = tmp_path / "workspaces"
    monkeypatch.setattr(dbpath, "WORKSPACES_DIR", root)
    return root


def test_create_workspace_writes_manifest(workspaces_root: Path) -> None:
    manifest = ws_mod.create_workspace(
        "obs-family", label="ATProto observatory family",
    )

    assert manifest["id"] == "obs-family"
    assert manifest["label"] == "ATProto observatory family"
    assert manifest["projects"] == []
    assert "created_at" in manifest

    manifest_path = workspace_manifest_path("obs-family")
    assert manifest_path.exists()
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk == manifest


def test_create_workspace_default_label(workspaces_root: Path) -> None:
    manifest = ws_mod.create_workspace("obs")
    assert manifest["label"] == "obs"


def test_create_duplicate_raises(workspaces_root: Path) -> None:
    ws_mod.create_workspace("dupe")
    with pytest.raises(ws_mod.WorkspaceExistsError):
        ws_mod.create_workspace("dupe")


def test_invalid_workspace_id(workspaces_root: Path) -> None:
    with pytest.raises(ValueError):
        ws_mod.create_workspace("")
    with pytest.raises(ValueError):
        ws_mod.create_workspace("with/slash")
    with pytest.raises(ValueError):
        ws_mod.create_workspace(".hidden")


def test_load_missing_workspace_raises(workspaces_root: Path) -> None:
    with pytest.raises(ws_mod.WorkspaceNotFoundError):
        ws_mod.load_workspace("nope")


def test_workspace_info_includes_paths(workspaces_root: Path) -> None:
    ws_mod.create_workspace("obs")
    info = ws_mod.workspace_info("obs")
    assert info["id"] == "obs"
    assert info["manifest_path"].endswith("obs/manifest.json")
    assert info["db_path"].endswith("obs/db.sqlite")
    assert info["db_exists"] is False


def test_list_workspace_summaries_empty(workspaces_root: Path) -> None:
    assert ws_mod.list_workspace_summaries() == []


def test_list_workspace_summaries(workspaces_root: Path) -> None:
    ws_mod.create_workspace("a", label="A")
    ws_mod.create_workspace("b", label="B")
    summaries = ws_mod.list_workspace_summaries()
    assert len(summaries) == 2
    ids = {s["id"] for s in summaries}
    assert ids == {"a", "b"}


def test_add_and_remove_project(workspaces_root: Path) -> None:
    ws_mod.create_workspace("obs")
    m1 = ws_mod.add_project_to_workspace("obs", "/home/u/git/driftwatch")
    assert "/home/u/git/driftwatch" in m1["projects"]

    # Idempotent — adding the same path again does nothing
    m2 = ws_mod.add_project_to_workspace("obs", "/home/u/git/driftwatch")
    assert m2["projects"].count("/home/u/git/driftwatch") == 1

    m3 = ws_mod.remove_project_from_workspace("obs", "/home/u/git/driftwatch")
    assert "/home/u/git/driftwatch" not in m3["projects"]


def test_resolve_workspace_via_arg(workspaces_root: Path) -> None:
    db, source = resolve_db_path(workspace="obs", env={}, cwd=workspaces_root.parent)
    assert source == "workspace"
    assert db == workspace_db_path("obs")


def test_resolve_workspace_via_env(workspaces_root: Path) -> None:
    db, source = resolve_db_path(
        env={"CONTINUITY_WORKSPACE": "obs"},
        cwd=workspaces_root.parent,
    )
    assert source == "workspace"
    assert db == workspace_db_path("obs")


def test_workspace_loses_to_explicit(workspaces_root: Path) -> None:
    p = workspaces_root.parent / "explicit.db"
    db, source = resolve_db_path(explicit=p, workspace="obs", env={})
    assert source == "explicit"
    assert db == p


def test_workspace_loses_to_env_db(workspaces_root: Path) -> None:
    db, source = resolve_db_path(
        workspace="obs",
        env={"CONTINUITY_DB_PATH": "/tmp/x.db"},
    )
    assert source == "env"
    assert db == Path("/tmp/x.db")


def test_workspace_beats_git_root(workspaces_root: Path, tmp_path: Path) -> None:
    repo = tmp_path / "myproj"
    repo.mkdir()
    (repo / ".git").mkdir()

    db, source = resolve_db_path(workspace="obs", env={}, cwd=repo)
    assert source == "workspace"
    assert db == workspace_db_path("obs")


def test_source_to_scope_kind_mapping() -> None:
    assert source_to_scope_kind("explicit") == "explicit"
    assert source_to_scope_kind("env") == "explicit"
    assert source_to_scope_kind("workspace") == "workspace"
    assert source_to_scope_kind("git-root") == "project"
    assert source_to_scope_kind("global-fallback") == "global"


def test_list_workspaces_dbpath_helper(workspaces_root: Path) -> None:
    ws_mod.create_workspace("first")
    ws_mod.create_workspace("second")
    # Also create a stray dir without manifest — should be ignored
    (workspaces_root / "stray").mkdir()
    listing = list_workspaces()
    assert listing == ["first", "second"]
