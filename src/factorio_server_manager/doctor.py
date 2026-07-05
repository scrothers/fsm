"""Preflight health checks for ``fsm doctor``.

Each check returns a :class:`Check` with a status of ``ok``, ``warn`` or
``fail``. Checks are best-effort and tolerant of a missing systemd / non-Linux
environment (so the suite and a workstation can run them), reporting ``warn``
rather than crashing. ``run`` returns the full list; the CLI prints it and exits
non-zero if any check fails.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

from . import binary, config, net, paths

#: A single check result. ``status`` is one of ``ok`` / ``warn`` / ``fail``.
Check = namedtuple("Check", "name status detail")

#: Warn when the home filesystem has less than this much free space.
MIN_FREE_BYTES = 2 * 1024**3


def check_python() -> Check:
    """Python must be 3.11+ (a hard requirement)."""
    if sys.version_info >= (3, 11):
        version = ".".join(map(str, sys.version_info[:3]))
        return Check("python", "ok", f"Python {version}")
    return Check("python", "fail", "Python 3.11+ required")


def check_linger() -> Check:
    """Lingering must be enabled so user units survive logout / start on boot."""
    user = getpass.getuser()
    if Path("/var/lib/systemd/linger", user).exists():
        return Check("linger", "ok", f"enabled for {user}")
    return Check(
        "linger",
        "warn",
        f"not enabled; run 'sudo loginctl enable-linger {user}'",
    )


def check_systemd() -> Check:
    """The systemd user manager should be reachable."""
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return Check("systemd", "warn", "systemctl not found")
    state = (result.stdout or result.stderr).strip()
    if state in ("running", "degraded", "starting"):
        return Check("systemd", "ok", f"user manager {state}")
    return Check("systemd", "warn", f"user manager: {state or 'unreachable'}")


def check_credentials() -> Check:
    """Account credentials are needed for mod downloads / public listing."""
    try:
        config.load_credentials()
    except config.ConfigError as exc:
        return Check("credentials", "warn", str(exc))
    return Check("credentials", "ok", str(paths.secrets_file()))


def check_current_build() -> Check:
    """At least one build should be installed and current."""
    version = binary.current_version()
    if version and paths.binary_path(paths.build_dir(version)).exists():
        return Check("current-build", "ok", f"factorio {version}")
    if version:
        return Check("current-build", "fail", f"current -> {version} but binary missing")
    return Check("current-build", "warn", "no build installed (fsm binary install)")


def check_disk() -> Check:
    """The home filesystem should have room for the build and mod pools."""
    try:
        usage = shutil.disk_usage(paths.home())
    except OSError as exc:
        return Check("disk", "warn", str(exc))
    free_gb = usage.free / 1024**3
    status = "ok" if usage.free >= MIN_FREE_BYTES else "warn"
    return Check("disk", status, f"{free_gb:.1f} GiB free at {paths.home()}")


def check_cgroup_delegation() -> Check:
    """Report which cgroup controllers back the ``performance:`` limits."""
    path = Path(
        f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice"
        f"/user@{os.getuid()}.service/cgroup.controllers"
    )
    try:
        controllers = set(path.read_text().split())
    except OSError:
        return Check("cgroup", "warn", "could not determine delegated controllers")
    wanted = {"cpu", "io", "memory"}
    have = wanted & controllers
    missing = wanted - controllers
    if not missing:
        return Check("cgroup", "ok", "cpu, io, memory delegated")
    return Check(
        "cgroup",
        "warn",
        f"delegated: {', '.join(sorted(have)) or 'none'}; "
        f"missing {', '.join(sorted(missing))} (some performance limits ignored)",
    )


def check_portal() -> Check:
    """Optional online check: can we reach factorio.com?"""
    try:
        with net.urlopen(binary.LATEST_RELEASES_URL, timeout=15):
            pass
    except OSError as exc:
        return Check("portal", "warn", f"cannot reach factorio.com: {exc}")
    return Check("portal", "ok", "factorio.com reachable")


#: Checks always run, in display order.
CHECKS = (
    check_python,
    check_linger,
    check_systemd,
    check_credentials,
    check_current_build,
    check_disk,
    check_cgroup_delegation,
)


def run(online: bool = False) -> list[Check]:
    """Run all checks (plus the portal check when ``online``)."""
    results = [check() for check in CHECKS]
    if online:
        results.append(check_portal())
    return results


def render(results: list[Check]) -> str:
    """Format check results as an aligned status list."""
    symbols = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}
    width = max((len(r.name) for r in results), default=0)
    return "\n".join(
        f"[{symbols.get(r.status, r.status)}] {r.name.ljust(width)}  {r.detail}"
        for r in results
    )
