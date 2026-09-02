"""Shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def mini_workspace(tmp_path: Path) -> Path:
    """A writable copy of ``fixtures/mini_repo`` (so runs can drop ``.pasr/``)."""
    root = tmp_path / "ws"
    shutil.copytree(_FIXTURES / "mini_repo", root)
    return root


@pytest.fixture
def trace_workspace(tmp_path: Path) -> Path:
    """A writable copy of ``fixtures/trace_repo``."""
    root = tmp_path / "ws"
    shutil.copytree(_FIXTURES / "trace_repo", root)
    return root
