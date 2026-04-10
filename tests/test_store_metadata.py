"""Tests for store_metadata: per-DB identity and provenance."""

from __future__ import annotations

from pathlib import Path

from continuity.store.sqlite import SQLiteStore


def test_metadata_populated_on_init(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    store = SQLiteStore(db)
    store.initialize()

    meta = store.get_store_metadata()
    assert meta is not None
    assert meta["store_id"].startswith("store_")
    assert meta["created_at"] is not None
    # Not in a git repo (tmp_path has no .git)
    assert meta["git_root"] is None
    # project_hint falls back to db dir name
    assert meta["project_hint"] == tmp_path.name


def test_metadata_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    store = SQLiteStore(db)
    store.initialize()
    meta1 = store.get_store_metadata()

    # Re-initialize: should not overwrite
    store.initialize()
    meta2 = store.get_store_metadata()

    assert meta1 == meta2


def test_metadata_includes_git_root_when_in_repo(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".continuity").mkdir()
    db = repo / ".continuity" / "db.sqlite"

    store = SQLiteStore(db)
    store.initialize()

    meta = store.get_store_metadata()
    assert meta is not None
    assert meta["git_root"] == str(repo.resolve())
    assert meta["project_hint"] == "myrepo"


def test_metadata_uses_dir_name_when_not_in_repo(tmp_path: Path) -> None:
    odd_dir = tmp_path / "weird-store-location"
    odd_dir.mkdir()
    db = odd_dir / "thing.db"
    store = SQLiteStore(db)
    store.initialize()

    meta = store.get_store_metadata()
    assert meta is not None
    assert meta["git_root"] is None
    assert meta["project_hint"] == "weird-store-location"


def test_metadata_distinct_across_stores(tmp_path: Path) -> None:
    s1 = SQLiteStore(tmp_path / "a.db")
    s1.initialize()
    s2 = SQLiteStore(tmp_path / "b.db")
    s2.initialize()

    m1 = s1.get_store_metadata()
    m2 = s2.get_store_metadata()
    assert m1 is not None and m2 is not None
    assert m1["store_id"] != m2["store_id"]
