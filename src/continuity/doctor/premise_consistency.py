"""Premise-consistency doctor.

Walks a directory of markdown memory files, follows `[[premise-name]]`
wikilink references, and flags entries whose wording weakens or omits
the operational obligation of any cited premise.

Read-only. The doctor reports; it does not resolve. Per
docs/gaps/PREMISE_CONSISTENCY_DOCTOR.md self-subject-collapse
discipline, this module makes no writes to the memory store, mutates
no memory records, and emits no findings that close, ratify, or
auto-resolve their own flags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# YAML frontmatter delimited by --- ... --- at file top.
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# `name: some-slug-here` inside the frontmatter block.
NAME_RE = re.compile(r"^name:\s*([A-Za-z0-9_\-]+)\s*$", re.MULTILINE)
# Wikilink: [[slug]] with hyphen/underscore-safe slugs.
LINK_RE = re.compile(r"\[\[([A-Za-z0-9_\-]+)\]\]")

# Words that mark an obligation being imposed.
OBLIGATION_TOKENS: tuple[str, ...] = (
    "must",
    "required",
    "binding",
    "obligatory",
    "mandatory",
    "shall",
    "non-negotiable",
    "load-bearing",
)

# Multi-word phrases that should be matched literally rather than at
# word boundaries.
OBLIGATION_PHRASES: tuple[str, ...] = (
    "must consult",
    "load-bearing",
)

# Words that mark an obligation being softened or made optional.
SOFTENING_TOKENS: tuple[str, ...] = (
    "may",
    "optional",
    "optionally",
    "advisory",
    "ambient",
    "non-binding",
    "suggested",
)

SOFTENING_PHRASES: tuple[str, ...] = (
    "if convenient",
    "where applicable",
    "should consider",
)

# Words a premise uses when it ships an instantiation mechanism the
# child is supposed to carry. Used only when the premise also imposes
# an obligation — otherwise descriptive uses ("the mechanism…")
# generate too much noise.
MECHANISM_TOKENS: tuple[str, ...] = (
    "stub",
    "hook",
    "lint",
    "instantiate",
    "instantiates",
    "wired",
    "wiring",
)


class FindingStatus(str, Enum):
    OK = "OK"
    FLAG = "FLAG"
    MISSING = "MISSING"


@dataclass
class Finding:
    status: FindingStatus
    child_file: Path
    child_name: str
    premise_slug: str
    premise_file: Path | None = None
    reason: str | None = None
    evidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status.value,
            "child_file": str(self.child_file),
            "child_name": self.child_name,
            "premise_slug": self.premise_slug,
        }
        if self.premise_file is not None:
            d["premise_file"] = str(self.premise_file)
        if self.reason is not None:
            d["reason"] = self.reason
        if self.evidence:
            d["evidence"] = self.evidence
        return d


def parse_frontmatter_name(text: str) -> str | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    nm = NAME_RE.search(m.group(1))
    return nm.group(1) if nm else None


def _body(text: str) -> str:
    m = FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


def parse_links(text: str) -> list[str]:
    """Return ordered, deduped slugs referenced via `[[slug]]` in the body."""
    body = _body(text)
    seen: dict[str, None] = {}
    for slug in LINK_RE.findall(body):
        seen.setdefault(slug, None)
    return list(seen)


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _strip_links(text: str) -> str:
    """Replace `[[slug]]` with whitespace so keyword scans don't match
    inside slug names (e.g., 'hook' inside `[[rule-with-hook]]`)."""
    return LINK_RE.sub(" ", text)


def _match_token(text: str, tokens: tuple[str, ...], phrases: tuple[str, ...]) -> str | None:
    """Return the first matched token/phrase, or None.

    Single-word tokens require word boundaries (so "may" does not match
    "mayonnaise"). Multi-word phrases are matched literally. Link slugs
    are stripped before scanning so 'hook' inside `[[rule-with-hook]]`
    is not treated as a keyword.
    """
    low = _strip_links(text).lower()
    for phrase in phrases:
        if phrase in low:
            return phrase
    for tok in tokens:
        if re.search(rf"\b{re.escape(tok)}\b", low):
            return tok
    return None


def _premise_imposes_obligation(body: str) -> tuple[bool, str | None, str | None]:
    """Return (has_obligation, sentence, matched_token).

    Sentence is the paragraph excerpt containing the matched token —
    enough context to be operator-readable, no more.
    """
    for para in _split_paragraphs(body):
        match = _match_token(para, OBLIGATION_TOKENS, OBLIGATION_PHRASES)
        if match is not None:
            return True, para, match
    return False, None, None


def _premise_ships_mechanism(body: str) -> list[str]:
    """Return mechanism words present in the premise body."""
    low = _strip_links(body).lower()
    found: list[str] = []
    for tok in MECHANISM_TOKENS:
        if re.search(rf"\b{re.escape(tok)}\b", low):
            found.append(tok)
    return found


def _link_paragraph(body: str, slug: str) -> str | None:
    """Return the paragraph containing the first `[[slug]]` reference."""
    target = f"[[{slug}]]"
    for para in _split_paragraphs(body):
        if target in para:
            return para
    return None


def _child_softens_near_link(body: str, slug: str) -> tuple[bool, str | None, str | None]:
    """Return (softens, paragraph, matched_token) for the paragraph holding the link."""
    para = _link_paragraph(body, slug)
    if para is None:
        return False, None, None
    match = _match_token(para, SOFTENING_TOKENS, SOFTENING_PHRASES)
    if match is None:
        return False, None, None
    return True, para, match


def _child_carries_mechanism(body: str, mechanism_words: list[str]) -> bool:
    low = _strip_links(body).lower()
    return any(re.search(rf"\b{re.escape(tok)}\b", low) for tok in mechanism_words)


def check_premise_consistency(memory_dir: Path) -> list[Finding]:
    """Scan a memory directory and return per-link findings.

    Non-recursive — operates on top-level `.md` files matching the
    convention used by `~/.claude/projects/*/memory/`. Skips
    `MEMORY.md` (the index, not a memory).

    For each `[[slug]]` reference in a child memory:
      OK       — premise resolves; no obligation/softening conflict
                 detected by current heuristics.
      FLAG     — premise imposes an obligation; child softens it near
                 the link OR drops a mechanism the premise ships.
      MISSING  — no memory in `memory_dir` carries `name: slug`.
    """
    files = sorted(memory_dir.glob("*.md"))

    slug_to_file: dict[str, Path] = {}
    file_to_text: dict[Path, str] = {}
    file_to_name: dict[Path, str | None] = {}

    for f in files:
        text = f.read_text(encoding="utf-8")
        file_to_text[f] = text
        name = parse_frontmatter_name(text)
        file_to_name[f] = name
        if name is not None:
            slug_to_file[name] = f

    findings: list[Finding] = []
    for child_file in files:
        if child_file.name == "MEMORY.md":
            continue
        child_text = file_to_text[child_file]
        child_name = file_to_name[child_file] or child_file.stem
        child_body = _body(child_text)

        for slug in parse_links(child_text):
            premise_file = slug_to_file.get(slug)
            if premise_file is None:
                findings.append(Finding(
                    status=FindingStatus.MISSING,
                    child_file=child_file,
                    child_name=child_name,
                    premise_slug=slug,
                    reason=f"no memory in {memory_dir} carries name '{slug}'",
                ))
                continue

            premise_body = _body(file_to_text[premise_file])
            has_obl, premise_para, obl_token = _premise_imposes_obligation(premise_body)

            flagged = False
            if has_obl:
                softens, child_para, soft_token = _child_softens_near_link(
                    child_body, slug,
                )
                if softens:
                    findings.append(Finding(
                        status=FindingStatus.FLAG,
                        child_file=child_file,
                        child_name=child_name,
                        premise_slug=slug,
                        premise_file=premise_file,
                        reason=(
                            "child softens obligation cited by premise: "
                            f"premise asserts '{obl_token}'; child uses "
                            f"'{soft_token}' near the link"
                        ),
                        evidence={
                            "premise_phrase": premise_para or "",
                            "child_phrase": child_para or "",
                        },
                    ))
                    flagged = True

            if not flagged and has_obl:
                mech_words = _premise_ships_mechanism(premise_body)
                if mech_words and not _child_carries_mechanism(child_body, mech_words):
                    findings.append(Finding(
                        status=FindingStatus.FLAG,
                        child_file=child_file,
                        child_name=child_name,
                        premise_slug=slug,
                        premise_file=premise_file,
                        reason=(
                            "premise names a mechanism "
                            f"({', '.join(mech_words)}) the child does not carry"
                        ),
                        evidence={
                            "premise_phrase": premise_para or "",
                            "child_phrase": (
                                "child body mentions none of: "
                                + ", ".join(mech_words)
                            ),
                        },
                    ))
                    flagged = True

            if not flagged:
                findings.append(Finding(
                    status=FindingStatus.OK,
                    child_file=child_file,
                    child_name=child_name,
                    premise_slug=slug,
                    premise_file=premise_file,
                ))

    return findings
