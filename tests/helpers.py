"""Shared test helpers for building a fake server layout."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path


def make_build(home: Path, version: str, *, current: bool = False) -> Path:
    """Create a fake extracted build under ``home/server``."""
    build = home / "server" / f"factorio_{version}"
    base = build / "factorio" / "data" / "base"
    base.mkdir(parents=True)
    (base / "info.json").write_text(json.dumps({"version": version}))
    binary = build / "factorio" / "bin" / "x64"
    binary.mkdir(parents=True)
    (binary / "factorio").write_text("#!/bin/sh\n")
    if current:
        link = home / "server" / "current"
        link.symlink_to(f"factorio_{version}")
    return build


def make_credentials(home: Path) -> Path:
    """Write a credentials file into the fake layout."""
    path = home / "secrets" / "credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"username": "tester", "token": "deadbeef"}))
    return path


def make_default_world(home: Path) -> Path:
    """Write a placeholder default world into the fake layout."""
    path = home / "worlds" / "world.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK\x03\x04 fake save")
    return path


def headless_tarball(version: str) -> bytes:
    """Build an in-memory ``.tar.xz`` mimicking a headless release."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as tar:
        _add(tar, "factorio/data/base/info.json", json.dumps({"version": version}))
        _add(tar, "factorio/bin/x64/factorio", "#!/bin/sh\n")
    return buffer.getvalue()


def _add(tar: tarfile.TarFile, name: str, text: str) -> None:
    data = text.encode()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


class FakeResponse:
    """Minimal urlopen stand-in supporting the context-manager + read API."""

    def __init__(self, data: bytes):
        self._buffer = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False
