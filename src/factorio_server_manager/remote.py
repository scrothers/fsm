"""SSH / rsync helpers used by the local deployer.

Thin ``subprocess`` wrappers around the system ``ssh`` and ``rsync`` binaries;
no third-party SSH library. Run on the workstation, not the server.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class RemoteError(Exception):
    """Raised when a remote command or transfer fails."""


def target(user: str, host: str) -> str:
    """Return the ``user@host`` SSH target string."""
    return f"{user}@{host}"


def ssh(user: str, host: str, command: str) -> None:
    """Run a shell command on the remote host, raising on failure."""
    result = subprocess.run(
        ["ssh", target(user, host), command], check=False
    )
    if result.returncode != 0:
        raise RemoteError(f"ssh command failed ({result.returncode}): {command}")


def rsync(
    user: str,
    host: str,
    source: Path | str,
    dest: str,
    *,
    excludes: list[str] | None = None,
) -> None:
    """Rsync a local path to ``user@host:dest``, raising on failure.

    A trailing slash on ``source`` copies its contents (rsync semantics); pass
    ``source`` as a string with the intended trailing slash, since ``Path``
    would strip it. Only flags supported by the ubiquitous rsync 2.6.x (shipped
    on macOS) are used, so remote permission fixes are done via :func:`ssh`.
    """
    args = ["rsync", "-az"]
    for pattern in excludes or []:
        args += ["--exclude", pattern]
    args += [str(source), f"{target(user, host)}:{dest}"]
    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        raise RemoteError(f"rsync failed ({result.returncode}): {source} -> {dest}")


def rsync_pull(
    user: str,
    host: str,
    remote_src: str,
    local_dest: str,
    *,
    options: list[str] | None = None,
) -> None:
    """Rsync from ``user@host:remote_src`` down to a local path, raising on failure.

    ``options`` are extra rsync flags (e.g. include/exclude filters) inserted
    before the paths.
    """
    args = ["rsync", "-az", *(options or []), f"{target(user, host)}:{remote_src}", local_dest]
    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        raise RemoteError(f"rsync pull failed ({result.returncode}): {remote_src}")
