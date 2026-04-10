"""Workspace manifests and operations.

A workspace is a named cross-project working set. It exists as:

  ~/.config/continuity/workspaces/<id>/manifest.json
  ~/.config/continuity/workspaces/<id>/db.sqlite

The manifest is deliberately simple — id, label, optional project list,
created_at — and may grow over time. It is read-only metadata about the
workspace itself, not authoritative state for the projects inside it.

Workspaces are opted into explicitly. Continuity does not infer
workspace membership from cwd, git remotes, or folder names. The user
selects a workspace via:

  --workspace <id>          # CLI flag
  CONTINUITY_WORKSPACE=<id> # environment variable
  .mcp.json env             # per-project MCP server config
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from continuity.util.clock import isoformat_now
from continuity.util.dbpath import (
    WORKSPACES_DIR,
    list_workspaces,
    workspace_db_path,
    workspace_dir,
    workspace_manifest_path,
)


class WorkspaceExistsError(RuntimeError):
    pass


class WorkspaceNotFoundError(KeyError):
    pass


def create_workspace(
    workspace_id: str,
    *,
    label: str | None = None,
    projects: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new workspace directory and manifest.

    Raises WorkspaceExistsError if the workspace already exists. Does not
    create the SQLite database — that happens lazily on first use, like
    any other store.
    """
    if not workspace_id or "/" in workspace_id or workspace_id.startswith("."):
        raise ValueError(f"invalid workspace id: {workspace_id!r}")

    ws_dir = workspace_dir(workspace_id)
    manifest_path = workspace_manifest_path(workspace_id)
    if manifest_path.exists():
        raise WorkspaceExistsError(f"workspace already exists: {workspace_id}")

    ws_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": workspace_id,
        "label": label or workspace_id,
        "projects": projects or [],
        "created_at": isoformat_now(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_workspace(workspace_id: str) -> dict[str, Any]:
    """Load a workspace's manifest. Raises WorkspaceNotFoundError if missing."""
    manifest_path = workspace_manifest_path(workspace_id)
    if not manifest_path.exists():
        raise WorkspaceNotFoundError(workspace_id)
    return json.loads(manifest_path.read_text())


def workspace_info(workspace_id: str) -> dict[str, Any]:
    """Return manifest plus derived paths for a workspace."""
    manifest = load_workspace(workspace_id)
    return {
        **manifest,
        "manifest_path": str(workspace_manifest_path(workspace_id)),
        "db_path": str(workspace_db_path(workspace_id)),
        "db_exists": workspace_db_path(workspace_id).exists(),
    }


def add_project_to_workspace(workspace_id: str, project_path: str) -> dict[str, Any]:
    """Append a project path to a workspace manifest. Idempotent."""
    manifest = load_workspace(workspace_id)
    projects = list(manifest.get("projects") or [])
    if project_path not in projects:
        projects.append(project_path)
    manifest["projects"] = projects
    workspace_manifest_path(workspace_id).write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return manifest


def remove_project_from_workspace(
    workspace_id: str, project_path: str,
) -> dict[str, Any]:
    """Remove a project path from a workspace manifest. Idempotent."""
    manifest = load_workspace(workspace_id)
    projects = [p for p in (manifest.get("projects") or []) if p != project_path]
    manifest["projects"] = projects
    workspace_manifest_path(workspace_id).write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return manifest


def list_workspace_summaries() -> list[dict[str, Any]]:
    """Return a summary for each known workspace."""
    out: list[dict[str, Any]] = []
    for ws_id in list_workspaces():
        try:
            manifest = load_workspace(ws_id)
        except (WorkspaceNotFoundError, json.JSONDecodeError):
            continue
        out.append({
            "id": ws_id,
            "label": manifest.get("label", ws_id),
            "project_count": len(manifest.get("projects") or []),
            "db_path": str(workspace_db_path(ws_id)),
            "db_exists": workspace_db_path(ws_id).exists(),
        })
    return out
