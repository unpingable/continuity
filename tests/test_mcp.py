"""Test continuity MCP server tool handlers.

Tests the ContinuityMCPServer class directly (no stdio transport).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from continuity.mcp import ContinuityMCPServer


@pytest.fixture
def server(tmp_path: Path) -> ContinuityMCPServer:
    return ContinuityMCPServer(tmp_path / "test.db")


def test_list_tools(server: ContinuityMCPServer) -> None:
    tools = server.list_tools()
    names = {t["name"] for t in tools}
    assert "memory_observe" in names
    assert "memory_commit" in names
    assert "memory_revoke" in names
    assert "memory_query" in names
    assert "memory_get" in names
    assert "memory_explain" in names
    assert "memory_stats" in names


def test_observe(server: ContinuityMCPServer) -> None:
    result = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "fact",
        "basis": "direct_capture",
        "content": {"claim": "MCP works"},
    })

    assert "error" not in result
    assert result["status"] == "observed"
    assert result["memory_id"].startswith("mem_")
    assert result["receipt_id"].startswith("rcpt_")


def test_observe_and_get(server: ContinuityMCPServer) -> None:
    obs = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "note",
        "basis": "direct_capture",
        "content": {"note": "round trip"},
    })

    got = server.call_tool("memory_get", {
        "memory_id": obs["memory_id"],
    })

    assert "error" not in got
    assert got["memory_id"] == obs["memory_id"]
    assert got["content"]["note"] == "round trip"


def test_observe_and_commit(server: ContinuityMCPServer) -> None:
    obs = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "decision",
        "basis": "operator_assertion",
        "content": {"decision": "use MCP"},
    })

    cmt = server.call_tool("memory_commit", {
        "memory_id": obs["memory_id"],
        "reliance_class": "advisory",
        "note": "approved via MCP",
    })

    assert "error" not in cmt
    assert cmt["status"] == "committed"
    assert cmt["reliance_class"] == "advisory"


def test_revoke(server: ContinuityMCPServer) -> None:
    obs = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "hypothesis",
        "basis": "inference",
        "content": {"hypothesis": "wrong guess"},
    })

    rev = server.call_tool("memory_revoke", {
        "memory_id": obs["memory_id"],
        "reason": "it was wrong",
    })

    assert "error" not in rev
    assert rev["status"] == "revoked"


def test_query(server: ContinuityMCPServer) -> None:
    for i in range(3):
        server.call_tool("memory_observe", {
            "scope": "project-x",
            "kind": "note",
            "basis": "direct_capture",
            "content": {"note": f"item {i}"},
        })

    server.call_tool("memory_observe", {
        "scope": "project-y",
        "kind": "note",
        "basis": "direct_capture",
        "content": {"note": "other scope"},
    })

    result = server.call_tool("memory_query", {
        "scope": "project-x",
    })

    assert "error" not in result
    assert result["total"] == 3
    assert len(result["items"]) == 3


def test_query_by_kind(server: ContinuityMCPServer) -> None:
    server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "fact",
        "basis": "direct_capture",
        "content": {"fact": "one"},
    })
    server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "hypothesis",
        "basis": "inference",
        "content": {"hypothesis": "maybe"},
    })

    result = server.call_tool("memory_query", {
        "kind": "fact",
    })

    assert result["total"] == 1
    assert result["items"][0]["kind"] == "fact"


def test_explain(server: ContinuityMCPServer) -> None:
    obs = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "fact",
        "basis": "direct_capture",
        "content": {"fact": "explainable"},
    })

    result = server.call_tool("memory_explain", {
        "memory_id": obs["memory_id"],
    })

    assert "error" not in result
    assert result["rely_ok"] is False
    assert result["memory"]["memory_id"] == obs["memory_id"]
    assert result["event_count"] == 1


def test_explain_with_premises(server: ContinuityMCPServer) -> None:
    fact = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "fact",
        "basis": "direct_capture",
        "content": {"fact": "premise"},
    })

    note = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "note",
        "basis": "inference",
        "content": {"note": "derived"},
        "premises": [
            {"memory_id": fact["memory_id"], "relation": "depends_on", "strength": "hard"},
        ],
    })

    result = server.call_tool("memory_explain", {
        "memory_id": note["memory_id"],
    })

    assert len(result["premises"]) == 1
    assert result["premises"][0]["src_memory_id"] == fact["memory_id"]


def test_rely_ok_with_revoked_premise(server: ContinuityMCPServer) -> None:
    """The money shot: revoked premise taints dependent via MCP."""
    hyp = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "hypothesis",
        "basis": "inference",
        "content": {"hypothesis": "pool is leaking"},
    })
    server.call_tool("memory_commit", {
        "memory_id": hyp["memory_id"],
        "reliance_class": "advisory",
    })

    action = server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "next_action",
        "basis": "inference",
        "content": {"action": "restart pool hourly"},
        "premises": [
            {"memory_id": hyp["memory_id"], "relation": "depends_on", "strength": "hard"},
        ],
    })
    server.call_tool("memory_commit", {
        "memory_id": action["memory_id"],
        "reliance_class": "advisory",
    })

    # Before revocation: rely_ok
    before = server.call_tool("memory_explain", {
        "memory_id": action["memory_id"],
    })
    assert before["rely_ok"] is True

    # Revoke the hypothesis
    server.call_tool("memory_revoke", {
        "memory_id": hyp["memory_id"],
        "reason": "was DNS, not pool",
    })

    # After revocation: tainted
    after = server.call_tool("memory_explain", {
        "memory_id": action["memory_id"],
    })
    assert after["rely_ok"] is False
    assert "revoked" in after["rely_reason"]


def test_stats(server: ContinuityMCPServer) -> None:
    server.call_tool("memory_observe", {
        "scope": "test",
        "kind": "fact",
        "basis": "direct_capture",
        "content": {"fact": "countable"},
    })

    result = server.call_tool("memory_stats", {})

    assert "error" not in result
    assert result["memories"] == 1
    assert result["events"] == 1
    assert result["receipts"] == 1


def test_unknown_tool(server: ContinuityMCPServer) -> None:
    result = server.call_tool("nonexistent_tool", {})
    assert "error" in result


def test_not_found_error(server: ContinuityMCPServer) -> None:
    result = server.call_tool("memory_get", {
        "memory_id": "mem_does_not_exist_at_all_nope",
    })
    assert "error" in result
    assert "not found" in result["error"]


def test_project_state_via_mcp(server: ContinuityMCPServer) -> None:
    """Dogfood: project_state through MCP tools."""
    obs = server.call_tool("memory_observe", {
        "scope": "governor-ecosystem",
        "kind": "project_state",
        "basis": "operator_assertion",
        "content": {
            "project": "continuity",
            "status": "active",
            "last_touch_summary": "MCP server working",
            "next_action": "integrate with Claude Code",
            "depends_on": ["governor"],
            "tags": ["foundation"],
            "provisional": False,
        },
    })

    cmt = server.call_tool("memory_commit", {
        "memory_id": obs["memory_id"],
        "reliance_class": "advisory",
    })

    query = server.call_tool("memory_query", {
        "scope": "governor-ecosystem",
        "kind": "project_state",
        "status": "committed",
    })

    assert query["total"] == 1
    assert query["items"][0]["content"]["project"] == "continuity"
