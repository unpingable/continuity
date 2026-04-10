"""Test contctl CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from continuity.cli import main


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


def run(db_path: str, argv: list[str]) -> str:
    """Run contctl and capture stdout."""
    import io
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        main(["--db", db_path] + argv)
    return buf.getvalue()


def run_json(db_path: str, argv: list[str]) -> dict:
    return json.loads(run(db_path, argv))


def test_init(db_path: str) -> None:
    output = run(db_path, ["init"])
    assert "initialized" in output


def test_observe_and_get(db_path: str) -> None:
    run(db_path, ["init"])

    result = run_json(db_path, [
        "observe",
        "--scope", "test-project",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"claim": "the sky is blue"}',
    ])

    assert result["status"] == "observed"
    mem_id = result["memory_id"]
    assert mem_id.startswith("mem_")

    # get it back
    got = run_json(db_path, ["get", mem_id])
    assert got["memory_id"] == mem_id
    assert got["content"]["claim"] == "the sky is blue"


def test_observe_quiet(db_path: str) -> None:
    run(db_path, ["init"])
    output = run(db_path, [
        "observe", "-q",
        "--scope", "test",
        "--kind", "note",
        "--basis", "direct_capture",
        "--content", '{"note": "quiet mode"}',
    ])
    assert output.strip().startswith("mem_")
    assert "\n" not in output.strip()


def test_where_human(db_path: str) -> None:
    run(db_path, ["init"])
    output = run(db_path, ["where"])
    assert "db_path:" in output
    assert "source:       explicit" in output
    assert "store_id:" in output


def test_where_json(db_path: str) -> None:
    run(db_path, ["init"])
    info = run_json(db_path, ["where", "--json"])
    assert info["db_path"] == db_path
    assert info["source"] == "explicit"
    assert info["exists"] is True
    assert info["metadata"]["store_id"].startswith("store_")


def test_case_command_human(db_path: str) -> None:
    """contctl case <scope> renders a human-readable bundle."""
    run(db_path, ["init"])

    # Build a small case
    summary_id = run_json(db_path, [
        "observe",
        "--scope", "case:demo",
        "--kind", "summary",
        "--basis", "direct_capture",
        "--content", '{"title": "Demo Case", "status": "open"}',
    ])["memory_id"]
    run(db_path, ["commit", summary_id, "--reliance-class", "advisory"])

    fact_id = run_json(db_path, [
        "observe",
        "--scope", "case:demo",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"text": "demo finding"}',
    ])["memory_id"]
    run(db_path, ["commit", fact_id, "--reliance-class", "actionable"])

    run(db_path, [
        "observe",
        "--scope", "case:demo",
        "--kind", "experiment",
        "--basis", "direct_capture",
        "--content", '{"action": "ran the test"}',
    ])

    output = run(db_path, ["case", "case:demo"])

    assert "Demo Case" in output
    assert "summary" in output
    assert "facts" in output
    assert "experiments" in output
    assert "demo finding" in output
    assert "ran the test" in output


def test_case_command_json(db_path: str) -> None:
    run(db_path, ["init"])
    run(db_path, [
        "observe",
        "--scope", "case:json-out",
        "--kind", "lesson",
        "--basis", "inference",
        "--content", '{"text": "always check framing"}',
    ])

    bundle = run_json(db_path, ["case", "case:json-out", "--json"])
    assert bundle["scope"] == "case:json-out"
    assert bundle["total_memories"] == 1
    assert len(bundle["lessons"]) == 1


def test_case_command_empty_scope(db_path: str) -> None:
    run(db_path, ["init"])
    output = run(db_path, ["case", "case:nothing-here"])
    assert "case:nothing-here" in output
    assert "total memories: 0" in output


def test_observe_with_receipt(db_path: str) -> None:
    run(db_path, ["init"])
    result = run_json(db_path, [
        "observe", "--receipt",
        "--scope", "test",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"fact": "receipts work"}',
    ])
    assert result["envelope"] == "continuity.receipt.v0"
    assert result["receipt_type"] == "memory.observe"
    assert "hash" in result
    assert "payload" in result


def test_observe_key_value_content(db_path: str) -> None:
    run(db_path, ["init"])
    result = run_json(db_path, [
        "observe",
        "--scope", "test",
        "--kind", "note",
        "--basis", "direct_capture",
        "--content", "claim=sky is blue,color=blue",
    ])
    mem_id = result["memory_id"]
    got = run_json(db_path, ["get", mem_id])
    assert got["content"]["claim"] == "sky is blue"
    assert got["content"]["color"] == "blue"


def test_commit(db_path: str) -> None:
    run(db_path, ["init"])

    obs = run_json(db_path, [
        "observe",
        "--scope", "test",
        "--kind", "decision",
        "--basis", "operator_assertion",
        "--content", '{"decision": "use SQLite"}',
    ])

    result = run_json(db_path, [
        "commit", obs["memory_id"],
        "--reliance-class", "advisory",
        "--actor", "operator:jbeck",
        "--note", "reviewed and approved",
    ])

    assert result["status"] == "committed"
    assert result["reliance_class"] == "advisory"


def test_revoke(db_path: str) -> None:
    run(db_path, ["init"])

    obs = run_json(db_path, [
        "observe",
        "--scope", "test",
        "--kind", "hypothesis",
        "--basis", "inference",
        "--content", '{"hypothesis": "pool leak"}',
    ])

    result = run_json(db_path, [
        "revoke", obs["memory_id"],
        "--reason", "was actually DNS",
    ])

    assert result["status"] == "revoked"


def test_query_by_scope(db_path: str) -> None:
    run(db_path, ["init"])

    for i in range(3):
        run(db_path, [
            "observe", "-q",
            "--scope", "project-a",
            "--kind", "note",
            "--basis", "direct_capture",
            "--content", f'{{"note": "note {i}"}}',
        ])

    run(db_path, [
        "observe", "-q",
        "--scope", "project-b",
        "--kind", "note",
        "--basis", "direct_capture",
        "--content", '{"note": "other project"}',
    ])

    result = run_json(db_path, ["query", "--scope", "project-a"])
    assert result["total"] == 3


def test_query_ids_only(db_path: str) -> None:
    run(db_path, ["init"])

    run(db_path, [
        "observe", "-q",
        "--scope", "test",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"fact": "one"}',
    ])

    output = run(db_path, ["query", "--scope", "test", "--ids-only"])
    lines = output.strip().split("\n")
    assert len(lines) == 1
    assert lines[0].startswith("mem_")


def test_explain(db_path: str) -> None:
    run(db_path, ["init"])

    obs = run_json(db_path, [
        "observe",
        "--scope", "test",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"fact": "explainable"}',
    ])

    result = run_json(db_path, ["explain", obs["memory_id"]])
    assert result["memory"]["memory_id"] == obs["memory_id"]
    assert result["rely_ok"] is False  # not committed yet
    assert len(result["events"]) == 1
    assert len(result["receipts"]) == 1


def test_stats(db_path: str) -> None:
    run(db_path, ["init"])

    run(db_path, [
        "observe", "-q",
        "--scope", "test",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"fact": "countable"}',
    ])

    result = run_json(db_path, ["stats"])
    assert result["memories"] == 1
    assert result["events"] == 1
    assert result["receipts"] == 1


def test_observe_with_premise(db_path: str) -> None:
    run(db_path, ["init"])

    # Create a fact
    fact = run_json(db_path, [
        "observe",
        "--scope", "test",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"fact": "premise"}',
    ])

    # Create a note depending on the fact
    note = run_json(db_path, [
        "observe",
        "--scope", "test",
        "--kind", "note",
        "--basis", "inference",
        "--content", '{"note": "depends on fact"}',
        "--premise", fact["memory_id"],
    ])

    # Explain should show the premise link
    explained = run_json(db_path, ["explain", note["memory_id"]])
    assert len(explained["premises"]) == 1
    assert explained["premises"][0]["src_memory_id"] == fact["memory_id"]


def test_observe_with_source_ref(db_path: str) -> None:
    run(db_path, ["init"])

    result = run_json(db_path, [
        "observe",
        "--scope", "test",
        "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"fact": "sourced"}',
        "--source-ref", "file:docs/arch.md:architecture doc",
    ])

    got = run_json(db_path, ["get", result["memory_id"]])
    assert len(got["source_refs"]) == 1
    assert got["source_refs"][0]["kind"] == "file"
    assert got["source_refs"][0]["ref"] == "docs/arch.md"


def test_project_state_workflow(db_path: str) -> None:
    """The dogfood test: observe and commit a project_state memory."""
    run(db_path, ["init"])

    obs = run_json(db_path, [
        "observe",
        "--scope", "governor-ecosystem",
        "--kind", "project_state",
        "--basis", "operator_assertion",
        "--content", json.dumps({
            "project": "continuity",
            "status": "active",
            "last_touch_summary": "slice 0 done, CLI in progress",
            "next_action": "dogfood project_state tracking",
            "depends_on": ["governor", "standing"],
            "tags": ["foundation"],
            "provisional": False,
        }),
        "--actor", "operator:jbeck",
    ])

    cmt = run_json(db_path, [
        "commit", obs["memory_id"],
        "--reliance-class", "advisory",
        "--actor", "operator:jbeck",
        "--note", "initial project state capture",
    ])

    assert cmt["status"] == "committed"
    assert cmt["reliance_class"] == "advisory"

    # Query for project_state
    result = run_json(db_path, [
        "query",
        "--scope", "governor-ecosystem",
        "--kind", "project_state",
    ])
    assert result["total"] == 1
    assert result["items"][0]["content"]["project"] == "continuity"


def test_nonexistent_memory_error(db_path: str) -> None:
    run(db_path, ["init"])
    with pytest.raises(SystemExit) as exc_info:
        run(db_path, ["get", "mem_does_not_exist_at_all"])
    assert exc_info.value.code == 1
