"""Dotted numeric version helpers shared across modules.

Factorio game and mod versions are simple dotted integers (``1.1.110``).
Kept dependency-free and importing nothing else in the package so any module
may use it without risking an import cycle.
"""

from __future__ import annotations


def version_tuple(version: str) -> tuple[int, ...]:
    """Parse a dotted numeric version into a comparable tuple of ints."""
    return tuple(int(part) for part in version.split("."))


def major_minor(version: str) -> str:
    """Return the ``major.minor`` prefix used to match mods to a game build."""
    parts = version.split(".")
    return ".".join(parts[:2])


def latest(versions: list[str]) -> str | None:
    """Return the highest version from a list, or ``None`` if empty."""
    if not versions:
        return None
    return max(versions, key=version_tuple)
