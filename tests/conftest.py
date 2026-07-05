"""Pytest fixtures pinning the manager layout to a temp directory."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # make helpers importable


@pytest.fixture
def fhome(tmp_path, monkeypatch):
    """Point ``FACTORIO_HOME`` (and the systemd config dir) at a temp directory."""
    monkeypatch.setenv("FACTORIO_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path
