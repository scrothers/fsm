"""Filesystem layout of the manager on the server.

Every path is derived from a single base directory, the ``factorio`` user's
home. Set ``FACTORIO_HOME`` to override it (used by the test suite). Nothing in
the package hardcodes ``/home/factorio``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Instance names become directory and unit-instance components; keep them to a
#: safe character set so they cannot traverse paths or inject into shell/unit
#: strings.
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def validate_name(name: str) -> str:
    """Return ``name`` if it is a safe instance identifier, else raise.

    :raises ValueError: if the name is empty or contains unsafe characters.
    """
    if not _NAME_RE.match(name or ""):
        raise ValueError(
            f"invalid instance name {name!r}: use letters, digits, '-' and '_'"
        )
    return name


def home() -> Path:
    """Return the manager base directory.

    Defaults to the current user's home; overridable via ``FACTORIO_HOME``.
    """
    override = os.environ.get("FACTORIO_HOME")
    return Path(override) if override else Path.home()


def server_dir() -> Path:
    """Directory holding the game version pool (every build kept forever)."""
    return home() / "server"


def channel_link(channel: str) -> Path:
    """Symlink naming a build pool channel (``current``/``stable``/``experimental``)."""
    return server_dir() / channel


def current_link() -> Path:
    """Symlink to the default build for instances that do not pin one."""
    return channel_link("current")


def build_dir(version: str) -> Path:
    """Directory of a specific extracted headless build."""
    return server_dir() / f"factorio_{version}"


def binary_path(build: Path) -> Path:
    """Path to the ``factorio`` executable inside an extracted build."""
    return build / "factorio" / "bin" / "x64" / "factorio"


def data_dir(build: Path) -> Path:
    """Path to the read-only ``data`` tree inside an extracted build."""
    return build / "factorio" / "data"


def mods_cache() -> Path:
    """Directory holding every mod version ever downloaded (kept forever)."""
    return home() / "mods-cache"


def mod_cache_dir(mod: str) -> Path:
    """Cache subdirectory for a single mod."""
    return mods_cache() / mod


def instances_dir() -> Path:
    """Directory holding every instance's runtime folder."""
    return home() / "instances"


def instance_dir(name: str) -> Path:
    """Runtime folder for a single instance."""
    return instances_dir() / validate_name(name)


def instance_config(name: str) -> Path:
    """Authored YAML for an instance (source of truth)."""
    return instance_dir(name) / "instance.yaml"


def instance_runtime(name: str) -> Path:
    """Generated runtime facts consumed by ``fsm run``."""
    return instance_dir(name) / "instance.json"


def instance_mods(name: str) -> Path:
    """Per-instance mod directory (holds symlinks into the cache)."""
    return instance_dir(name) / "mods"


def instance_saves(name: str) -> Path:
    """Per-instance saves directory."""
    return instance_dir(name) / "saves"


def secrets_file() -> Path:
    """Factorio account credentials used for authenticated mod downloads."""
    return home() / "secrets" / "credentials.json"


def default_world() -> Path:
    """Shared default world seeded into new instances."""
    return home() / "worlds" / "world.zip"
