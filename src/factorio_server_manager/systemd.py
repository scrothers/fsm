"""Installation of the ``factorio@.service`` user template unit and per-instance
performance drop-ins.

The unit ships as package data and is copied into the user's systemd directory.
Per-instance resource controls (CPU affinity, priority, cgroup limits) are
written as a drop-in under ``factorio@<instance>.service.d/`` so the shared
template stays untouched.
"""

from __future__ import annotations

import os
import subprocess
from importlib import resources
from pathlib import Path

from . import paths

UNIT_NAME = "factorio@.service"

#: Name of the drop-in file the manager owns (leaves other drop-ins alone).
PERF_DROPIN = "performance.conf"

#: Scheduled-maintenance units (service + timer pairs) shipped as templates.
TIMER_UNITS = (
    "fsm-mods-refresh.service",
    "fsm-mods-refresh.timer",
    "fsm-binary-update.service",
    "fsm-binary-update.timer",
)


def _template_text(name: str) -> str:
    """Return the contents of a packaged systemd template."""
    return (
        resources.files("factorio_server_manager.templates").joinpath(name).read_text()
    )


def unit_text() -> str:
    """Return the packaged ``factorio@.service`` contents."""
    return _template_text(UNIT_NAME)


def unit_dir() -> Path:
    """Return the user's systemd unit directory, creating it if needed.

    Derived from the manager home so it matches the server layout (where home is
    the ``factorio`` user) and stays isolated under ``FACTORIO_HOME`` in tests;
    ``XDG_CONFIG_HOME`` still wins if the user sets it.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(paths.home() / ".config")
    path = Path(base) / "systemd" / "user"
    path.mkdir(parents=True, exist_ok=True)
    return path


def instance_dropin(instance: str) -> Path:
    """Path to the manager's performance drop-in for an instance."""
    return unit_dir() / f"factorio@{instance}.service.d" / PERF_DROPIN


def _env() -> dict:
    """Environment with ``XDG_RUNTIME_DIR`` so ``systemctl --user`` works."""
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def _systemctl(*args: str) -> None:
    """Best-effort ``systemctl --user`` (no-op when systemctl is absent)."""
    try:
        subprocess.run(["systemctl", "--user", *args], env=_env(), check=False)
    except FileNotFoundError:
        pass  # systemctl absent (e.g. developer workstation)


def _daemon_reload() -> None:
    """Best-effort ``systemctl --user daemon-reload``."""
    _systemctl("daemon-reload")


def install() -> Path:
    """Install the ``factorio@.service`` unit and reload the user manager."""
    target = unit_dir() / UNIT_NAME
    target.write_text(unit_text())
    _daemon_reload()
    return target


def install_timers() -> list[Path]:
    """Install and enable the scheduled-maintenance timers.

    Installs the service+timer pairs (mod refresh and channel update) and enables
    the timers so the pools stay fresh unattended.

    :returns: the installed unit paths.
    """
    installed = []
    for name in TIMER_UNITS:
        target = unit_dir() / name
        target.write_text(_template_text(name))
        installed.append(target)
    _daemon_reload()
    for name in TIMER_UNITS:
        if name.endswith(".timer"):
            _systemctl("enable", "--now", name)
    return installed


def remove_dropin(instance: str) -> None:
    """Remove an instance's performance drop-in (and empty dir) and reload."""
    path = instance_dropin(instance)
    if path.exists():
        path.unlink()
    parent = path.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
    _daemon_reload()


def apply_dropin(instance: str, directives: dict[str, str]) -> Path | None:
    """Write (or remove) an instance's performance drop-in and reload.

    :param directives: systemd ``[Service]`` keys to set; empty removes the
        drop-in so stale limits do not linger.
    :returns: the drop-in path when written, else ``None``.
    """
    path = instance_dropin(instance)
    if directives:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "[Service]\n" + "".join(f"{k}={v}\n" for k, v in directives.items())
        path.write_text(body)
        result = path
    else:
        if path.exists():
            path.unlink()
        result = None
    _daemon_reload()
    return result
