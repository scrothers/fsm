"""The game version pool: download and retain every headless build.

Builds are extracted into ``server/factorio_<ver>/`` and never removed. The
``server/current`` symlink names the default build for instances that do not
pin a specific version.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
from pathlib import Path

from . import net, paths
from .semver import version_tuple

DOWNLOAD_URL = "https://factorio.com/get-download/{version}/headless/linux64"
LATEST_RELEASES_URL = "https://factorio.com/api/latest-releases"

#: Network timeout (seconds) for the build download.
HTTP_TIMEOUT = 120

#: Download tokens that name a release channel, mapped to the channel symlink
#: they maintain. ``latest`` is factorio.com's alias for experimental.
CHANNELS = {"stable": "stable", "experimental": "experimental", "latest": "experimental"}

#: Channel symlinks maintained in the pool, in display order.
CHANNEL_NAMES = ("current", "stable", "experimental")


class BinaryError(Exception):
    """Raised when a build cannot be downloaded, extracted or resolved."""


def installed_versions() -> list[str]:
    """Return every installed build version, newest first."""
    server = paths.server_dir()
    if not server.is_dir():
        return []
    versions = []
    for child in server.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        if child.name.startswith("factorio_"):
            versions.append(child.name[len("factorio_"):])
    return sorted(versions, key=version_tuple, reverse=True)


def link_version(channel: str) -> str | None:
    """Return the version a channel symlink points at, or ``None``."""
    link = paths.channel_link(channel)
    if not link.is_symlink():
        return None
    name = link.resolve().name
    return name[len("factorio_"):] if name.startswith("factorio_") else None


def current_version() -> str | None:
    """Return the version the ``current`` symlink points at, if any."""
    return link_version("current")


def channels() -> dict[str, str]:
    """Map each existing channel symlink to the version it points at."""
    return {
        name: version
        for name in CHANNEL_NAMES
        if (version := link_version(name)) is not None
    }


def _extracted_version(build: Path) -> str:
    """Read the exact version from a freshly extracted build's base mod."""
    info = paths.data_dir(build) / "base" / "info.json"
    with info.open() as handle:
        return json.load(handle)["version"]


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract a tarball safely across Python versions.

    Uses tarfile's ``data`` filter where available (Python 3.12+, and the 3.9-3.11
    security backports). On older interpreters that predate the filter API
    (e.g. Debian 12's stock Python 3.11.2) it validates each member's path is
    contained within ``dest`` before extracting.
    """
    if hasattr(tarfile, "data_filter"):
        tar.extractall(dest, filter="data")
        return
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if target != dest and dest not in target.parents:
            raise BinaryError(f"unsafe path in archive: {member.name}")
    tar.extractall(dest)  # noqa: S202 - members validated above


def install(version: str = "stable", *, make_current: bool = False) -> str:
    """Download and extract a headless build into the pool.

    ``version`` may be a concrete version, ``stable`` or ``latest``; the exact
    installed version is read from the extracted build. Re-installing an
    already-present build is a no-op download.

    :returns: the concrete version installed.
    """
    paths.server_dir().mkdir(parents=True, exist_ok=True)
    url = DOWNLOAD_URL.format(version=version)
    with tempfile.TemporaryDirectory(dir=paths.server_dir()) as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "headless.tar.xz"
        with net.urlopen(url, timeout=HTTP_TIMEOUT) as response, \
                archive.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        with tarfile.open(archive, "r:xz") as tar:
            _safe_extract(tar, tmp_path)
        extracted = tmp_path / "factorio"
        if not extracted.is_dir():
            raise BinaryError("archive did not contain a 'factorio' directory")
        concrete = _extracted_version(tmp_path)
        build = paths.build_dir(concrete)
        if not build.exists():
            (build).mkdir(parents=True)
            extracted.rename(build / "factorio")
    channel = CHANNELS.get(version)
    if channel:
        set_channel(channel, concrete)
    if make_current or current_version() is None:
        set_channel("current", concrete)
    return concrete


def set_channel(channel: str, version: str) -> None:
    """Point a channel symlink (current/stable/experimental) at a build."""
    build = paths.build_dir(version)
    if not build.is_dir():
        raise BinaryError(f"version {version} is not installed")
    link = paths.channel_link(channel)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(build.name)


def set_current(version: str) -> None:
    """Point the ``current`` symlink at an installed build."""
    set_channel("current", version)


def latest_releases() -> dict:
    """Fetch factorio.com's latest published versions per channel."""
    with net.urlopen(LATEST_RELEASES_URL, timeout=HTTP_TIMEOUT) as response:
        return json.load(response)


def latest_channel_version(channel: str, releases: dict | None = None) -> str | None:
    """Return the newest published headless version for a channel."""
    releases = releases if releases is not None else latest_releases()
    return releases.get(channel, {}).get("headless")


def channel_game_versions(releases: dict | None = None) -> dict[str, str]:
    """Return the current stable and experimental headless game versions.

    :returns: ``{channel: version}`` for whichever of stable/experimental the
        portal reports.
    """
    releases = releases if releases is not None else latest_releases()
    return {
        channel: version
        for channel in ("stable", "experimental")
        if (version := releases.get(channel, {}).get("headless"))
    }


def update() -> list[tuple[str, str | None, str]]:
    """Refresh every opted-in channel to its latest published build.

    A channel is opted-in once its symlink exists (i.e. it has been installed at
    least once). For each such channel, the latest build is downloaded if not
    already in the pool and the symlink is repointed. Builds are kept forever.

    :returns: ``(channel, old_version, new_version)`` for channels that moved.
    """
    releases = latest_releases()
    changes: list[tuple[str, str | None, str]] = []
    for channel in ("stable", "experimental"):
        if not paths.channel_link(channel).is_symlink():
            continue  # channel not opted into
        latest = latest_channel_version(channel, releases)
        if not latest:
            continue
        current = link_version(channel)
        if latest == current and paths.build_dir(latest).is_dir():
            continue
        install(latest)
        set_channel(channel, latest)
        changes.append((channel, current, latest))
    return changes
