"""Tests for continuity.doctor.premise_consistency.

Acceptance criteria from docs/gaps/PREMISE_CONSISTENCY_DOCTOR.md:

- Dogfood fixture (pre-correction) flags as FLAG; post-correction clears.
- Missing premise link reports MISSING.
- Output cites premise file, child file, and the wording pair that
  triggered the flag.
- Self-subject-collapse discipline: doctor performs no writes — it
  returns findings; it does not mutate memory records. The module's
  public surface accepts a directory Path and returns Finding values;
  there is no write path to assert is unused, because there is no
  write path at all.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from continuity.doctor import (
    Finding,
    FindingStatus,
    check_premise_consistency,
)
from continuity.doctor.premise_consistency import (
    parse_frontmatter_name,
    parse_links,
)

FIXTURES = Path(__file__).parent / "fixtures" / "premise_consistency"


def _findings_for(memory_dir: Path) -> list[Finding]:
    return check_premise_consistency(memory_dir)


def _by_status(findings: list[Finding]) -> dict[FindingStatus, list[Finding]]:
    out: dict[FindingStatus, list[Finding]] = {
        s: [] for s in FindingStatus
    }
    for f in findings:
        out[f.status].append(f)
    return out


def test_frontmatter_name_parsing() -> None:
    text = (
        "---\n"
        "name: some-slug\n"
        "description: hi\n"
        "---\n"
        "\nbody\n"
    )
    assert parse_frontmatter_name(text) == "some-slug"


def test_frontmatter_name_missing_returns_none() -> None:
    assert parse_frontmatter_name("no frontmatter here") is None


def test_parse_links_deduped_and_ordered() -> None:
    text = (
        "---\nname: x\n---\n"
        "first [[alpha]] then [[beta]] and [[alpha]] again\n"
    )
    assert parse_links(text) == ["alpha", "beta"]


def test_dogfood_pre_flags() -> None:
    """Pre-correction child softens an obligation; doctor must FLAG."""
    findings = _findings_for(FIXTURES / "dogfood_pre")
    by_status = _by_status(findings)

    flags = by_status[FindingStatus.FLAG]
    assert len(flags) == 1, f"expected one FLAG, got {findings}"

    flag = flags[0]
    assert flag.premise_slug == "consultation-must-be-load-bearing"
    assert flag.premise_file is not None
    assert flag.premise_file.name == "premise_consultation_must_be_load_bearing.md"
    assert flag.child_file.name == "child_doctrine_promotion_optional.md"
    assert flag.reason is not None
    assert "softens" in flag.reason
    assert flag.evidence["premise_phrase"]
    assert flag.evidence["child_phrase"]
    # The evidence must include the operative phrase pair so an operator
    # can see what the doctor flagged on.
    assert "optional" in flag.evidence["child_phrase"].lower()


def test_dogfood_post_is_ok() -> None:
    """Post-correction child carries the obligation; doctor must report OK."""
    findings = _findings_for(FIXTURES / "dogfood_post")
    by_status = _by_status(findings)

    assert by_status[FindingStatus.FLAG] == []
    assert by_status[FindingStatus.MISSING] == []
    oks = by_status[FindingStatus.OK]
    assert len(oks) == 1
    assert oks[0].premise_slug == "consultation-must-be-load-bearing"
    assert oks[0].child_name == "doctrine-promotion-bound"


def test_missing_premise_link() -> None:
    findings = _findings_for(FIXTURES / "missing_link")
    by_status = _by_status(findings)

    missing = by_status[FindingStatus.MISSING]
    assert len(missing) == 1
    m = missing[0]
    assert m.premise_slug == "no-such-premise"
    assert m.premise_file is None
    assert m.reason is not None
    assert "no-such-premise" in m.reason


def test_neutral_descriptive_premise_is_ok() -> None:
    """A premise with no obligation language never produces a FLAG."""
    findings = _findings_for(FIXTURES / "neutral")
    by_status = _by_status(findings)
    assert by_status[FindingStatus.FLAG] == []
    assert by_status[FindingStatus.MISSING] == []
    assert len(by_status[FindingStatus.OK]) == 1


def test_dropped_mechanism_flags() -> None:
    """Premise that ships a mechanism flags children that don't carry it."""
    findings = _findings_for(FIXTURES / "dropped_mechanism")
    by_status = _by_status(findings)

    flags = by_status[FindingStatus.FLAG]
    assert len(flags) == 1, f"expected one FLAG, got {findings}"
    flag = flags[0]
    assert flag.premise_slug == "rule-with-hook"
    assert flag.reason is not None
    assert "mechanism" in flag.reason


def test_finding_to_dict_round_trip() -> None:
    findings = _findings_for(FIXTURES / "dogfood_pre")
    assert findings
    # to_dict produces JSON-serializable output.
    payload = [f.to_dict() for f in findings]
    blob = json.dumps(payload)
    parsed = json.loads(blob)
    assert parsed[0]["status"] in {"OK", "FLAG", "MISSING"}
    assert "child_file" in parsed[0]
    assert "premise_slug" in parsed[0]


def test_cli_dogfood_pre_exits_2_with_flag(tmp_path: Path) -> None:
    """`contctl doctor --check premise-consistency` returns exit code 2 on FLAG."""
    import subprocess

    result = subprocess.run(
        [
            "contctl", "doctor",
            "--check", "premise-consistency",
            "--json",
            str(FIXTURES / "dogfood_pre"),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["check"] == "premise-consistency"
    assert any(f["status"] == "FLAG" for f in payload["findings"])


def test_cli_dogfood_post_exits_0(tmp_path: Path) -> None:
    """`contctl doctor` exits 0 when nothing flags or misses."""
    import subprocess

    result = subprocess.run(
        [
            "contctl", "doctor",
            "--check", "premise-consistency",
            "--json",
            str(FIXTURES / "dogfood_post"),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert all(f["status"] == "OK" for f in payload["findings"])


def test_doctor_does_not_touch_sqlite_sibling(tmp_path: Path) -> None:
    """Self-subject-collapse discipline: no write side-effects.

    Place a SQLite file alongside a copy of a fixture; running the
    doctor must not modify the database. The interface accepts only
    a directory Path and returns in-memory findings — there is no
    write path. This test asserts the interface guarantee operationally.
    """
    # Copy the dogfood_pre fixture into tmp_path.
    src = FIXTURES / "dogfood_pre"
    dst = tmp_path / "memory"
    dst.mkdir()
    for f in src.glob("*.md"):
        (dst / f.name).write_bytes(f.read_bytes())

    db_path = tmp_path / "sibling.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sentinel (val TEXT)")
    conn.execute("INSERT INTO sentinel(val) VALUES ('untouched')")
    conn.commit()
    conn.close()
    before = db_path.read_bytes()

    findings = check_premise_consistency(dst)
    assert any(f.status == FindingStatus.FLAG for f in findings)

    after = db_path.read_bytes()
    assert before == after, "doctor must not write to a sibling SQLite store"
