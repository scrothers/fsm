"""Thin wrappers over ``systemctl --user`` / ``journalctl --user`` for instances.

Used interactively on the server. ``XDG_RUNTIME_DIR`` is set so ``--user`` works
over a non-interactive SSH session where systemd would not otherwise find the
user manager's socket.
"""

from __future__ import annotations

import os
import subprocess


def _unit(name: str) -> str:
    """Return the templated unit name for an instance."""
    return f"factorio@{name}"


def _env() -> dict:
    """Environment ensuring ``systemctl --user`` finds the user manager."""
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def _systemctl(*args: str) -> int:
    """Run ``systemctl --user`` and return its exit code."""
    return subprocess.run(
        ["systemctl", "--user", *args], env=_env(), check=False
    ).returncode


def start(name: str) -> int:
    """Start an instance now."""
    return _systemctl("start", _unit(name))


def stop(name: str) -> int:
    """Stop an instance (clean SIGINT save)."""
    return _systemctl("stop", _unit(name))


def enable(name: str) -> int:
    """Enable an instance to start on boot."""
    return _systemctl("enable", _unit(name))


def disable(name: str) -> int:
    """Disable an instance from starting on boot."""
    return _systemctl("disable", _unit(name))


def status(name: str) -> int:
    """Show an instance's unit status."""
    return _systemctl("status", _unit(name))


def logs(name: str, *, follow: bool = False) -> int:
    """Show an instance's journal, optionally following it."""
    args = ["journalctl", "--user", "-u", _unit(name)]
    if follow:
        args.append("-f")
    try:
        return subprocess.run(args, env=_env(), check=False).returncode
    except KeyboardInterrupt:
        return 0
