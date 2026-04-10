"""Tests for database path resolution."""

from __future__ import annotations

from pathlib import Path

from continuity.util.dbpath import (
    GLOBAL_DB_PATH,
    PROJECT_DB_RELATIVE,
    find_git_root,
    resolve_db_path,
)


def test_explicit_path_wins(tmp_path: Path) -> None:
    p = tmp_path / "explicit.db"
    db, source = resolve_db_path(explicit=p, env={}, cwd=tmp_path)
    assert db == p
    assert source == "explicit"


def test_env_var_wins_over_git_root(tmp_path: Path) -> None:
    # Set up a fake git repo
    (tmp_path / ".git").mkdir()
    env_db = tmp_path / "from-env.db"
    db, source = resolve_db_path(
        env={"CONTINUITY_DB_PATH": str(env_db)},
        cwd=tmp_path,
    )
    assert db == env_db
    assert source == "env"


def test_git_root_resolution(tmp_path: Path) -> None:
    repo = tmp_path / "myproject"
    repo.mkdir()
    (repo / ".git").mkdir()
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)

    db, source = resolve_db_path(env={}, cwd=sub)
    assert db == repo / PROJECT_DB_RELATIVE
    assert source == "git-root"


def test_global_fallback_when_not_in_repo(tmp_path: Path) -> None:
    # tmp_path has no .git anywhere up the tree by construction
    db, source = resolve_db_path(env={}, cwd=tmp_path)
    assert db == GLOBAL_DB_PATH
    assert source == "global-fallback"


def test_find_git_root_with_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b" / "c"
    sub.mkdir(parents=True)
    assert find_git_root(sub) == tmp_path.resolve()


def test_find_git_root_with_file(tmp_path: Path) -> None:
    """Worktrees have a .git file (not directory) pointing at the gitdir."""
    (tmp_path / ".git").write_text("gitdir: /elsewhere")
    sub = tmp_path / "nested"
    sub.mkdir()
    assert find_git_root(sub) == tmp_path.resolve()


def test_find_git_root_returns_none_outside_repo(tmp_path: Path) -> None:
    # tmp_path has no .git
    assert find_git_root(tmp_path) is None


def test_explicit_path_beats_env(tmp_path: Path) -> None:
    p = tmp_path / "explicit.db"
    env_db = tmp_path / "env.db"
    db, source = resolve_db_path(
        explicit=p,
        env={"CONTINUITY_DB_PATH": str(env_db)},
    )
    assert db == p
    assert source == "explicit"
