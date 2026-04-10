"""Database path resolution.

Resolution order, highest priority first:
  1. Explicit path argument (--db on CLI, db_path on MCP)
  2. CONTINUITY_DB_PATH environment variable
  3. <git-root>/.continuity/db.sqlite when inside a git repo
  4. Global fallback at ~/.local/share/continuity/continuity.db

This makes per-project DBs the default whenever you're working inside a
repo, while keeping standalone use possible. The global fallback only
fires when there is no surrounding git repo at all.
"""

from __future__ import annotations

import os
from pathlib import Path

GLOBAL_DB_PATH = Path.home() / ".local" / "share" / "continuity" / "continuity.db"
PROJECT_DB_RELATIVE = Path(".continuity") / "db.sqlite"
ENV_VAR = "CONTINUITY_DB_PATH"


def find_git_root(start: Path | None = None) -> Path | None:
    """Walk up from start (or cwd) looking for a .git directory or file.

    Returns the directory containing .git, or None if not in a git repo.
    A worktree's .git is a regular file pointing at the gitdir; both forms
    count as "inside a repo" for our purposes.
    """
    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def resolve_db_path(
    explicit: Path | str | None = None,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[Path, str]:
    """Resolve the active continuity DB path and label its source.

    The label is one of: 'explicit', 'env', 'git-root', 'global-fallback'.
    Callers can show this to operators so the active store is never
    ambiguous.
    """
    if explicit is not None:
        return Path(explicit), "explicit"

    env_map = env if env is not None else os.environ
    env_value = env_map.get(ENV_VAR)
    if env_value:
        return Path(env_value), "env"

    git_root = find_git_root(cwd)
    if git_root is not None:
        return git_root / PROJECT_DB_RELATIVE, "git-root"

    return GLOBAL_DB_PATH, "global-fallback"
