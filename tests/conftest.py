"""Shared test fixtures."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from continuity.store.sqlite import SQLiteStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    db = tmp_path / "test.db"
    s = SQLiteStore(db)
    s.initialize()
    return s
