"""Database path resolution.

Resolution order, highest priority first:
  1. Explicit path argument (--db on CLI, db_path on MCP)
  2. CONTINUITY_DB_PATH environment variable
  3. Explicit workspace selection (--workspace flag or CONTINUITY_WORKSPACE env)
  4. <git-root>/.continuity/db.sqlite when inside a git repo
  5. Global fallback at ~/.local/share/continuity/continuity.db

Three kinds of store are supported:

  project    repo-local, authoritative state for a single repo
  workspace  named cross-project working set, opted into explicitly
  global     user-level spillover, used sparingly

Workspace is the explicit answer to "this session's frame is bigger than
one repo." It is never inferred from cwd, git remotes, or folder names —
the user must opt in by env var, --workspace flag, or .mcp.json env.
"""

from __future__ import annotations

import os
from pathlib import Path

GLOBAL_DB_PATH = Path.home() / ".local" / "share" / "continuity" / "continuity.db"
PROJECT_DB_RELATIVE = Path(".continuity") / "db.sqlite"
WORKSPACES_DIR = Path.home() / ".config" / "continuity" / "workspaces"

ENV_DB = "CONTINUITY_DB_PATH"
ENV_WORKSPACE = "CONTINUITY_WORKSPACE"

# Backward-compat alias
ENV_VAR = ENV_DB


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


def workspace_dir(workspace_id: str) -> Path:
    """Return the directory holding a workspace's manifest and db."""
    return WORKSPACES_DIR / workspace_id


def workspace_db_path(workspace_id: str) -> Path:
    """Return the SQLite path for a named workspace."""
    return workspace_dir(workspace_id) / "db.sqlite"


def workspace_manifest_path(workspace_id: str) -> Path:
    """Return the manifest path for a named workspace."""
    return workspace_dir(workspace_id) / "manifest.json"


def list_workspaces() -> list[str]:
    """List workspace ids known on this machine.

    A workspace is any subdirectory of WORKSPACES_DIR that contains a
    manifest.json file. Subdirectories without a manifest are ignored.
    """
    if not WORKSPACES_DIR.exists():
        return []
    out: list[str] = []
    for child in sorted(WORKSPACES_DIR.iterdir()):
        if child.is_dir() and (child / "manifest.json").exists():
            out.append(child.name)
    return out


def resolve_db_path(
    explicit: Path | str | None = None,
    *,
    workspace: str | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[Path, str]:
    """Resolve the active continuity DB path and label its source.

    The label is one of:
      'explicit', 'env', 'workspace', 'git-root', 'global-fallback'.

    Callers can show this to operators so the active store is never
    ambiguous. Workspace selection (via the workspace argument or
    CONTINUITY_WORKSPACE env var) wins over git-root resolution but
    loses to explicit path or CONTINUITY_DB_PATH.
    """
    if explicit is not None:
        return Path(explicit), "explicit"

    env_map = env if env is not None else os.environ
    env_db = env_map.get(ENV_DB)
    if env_db:
        return Path(env_db), "env"

    ws_id = workspace or env_map.get(ENV_WORKSPACE)
    if ws_id:
        return workspace_db_path(ws_id), "workspace"

    git_root = find_git_root(cwd)
    if git_root is not None:
        return git_root / PROJECT_DB_RELATIVE, "git-root"

    return GLOBAL_DB_PATH, "global-fallback"


def source_to_scope_kind(source: str) -> str:
    """Map a resolver source label to a scope_kind for metadata."""
    return {
        "explicit": "explicit",
        "env": "explicit",
        "workspace": "workspace",
        "git-root": "project",
        "global-fallback": "global",
    }.get(source, "unknown")
