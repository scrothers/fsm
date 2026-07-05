"""Mod portal client and the cache-forever mod pool.

Every mod version ever downloaded is kept in ``mods-cache/<mod>/``. An
instance's ``mods/`` directory holds symlinks into that cache for exactly the
versions it uses, so Factorio loads the intended versions while the pool
retains all of them. Nothing here ever deletes a cache file.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

from . import net, paths
from .semver import major_minor, version_tuple

API_BASE = "https://mods.factorio.com"
API_FULL = API_BASE + "/api/mods/{name}/full"

#: Network timeout (seconds) for every portal request, so a hung connection
#: cannot stall the systemd ``ExecStartPre`` mod update indefinitely.
HTTP_TIMEOUT = 30

#: Mods shipped with the engine; never fetched from the portal.
BUILTIN = frozenset({"base", "space-age", "elevated-rails", "quality"})

#: Parse one Factorio dependency string: optional prefix, name, optional
#: version constraint. Prefixes: '!' incompatible, '?'/'(?)' optional, '~'
#: required-but-load-order-agnostic, none = required.
_DEP_RE = re.compile(
    r"\A\s*(?P<prefix>!|\(\?\)|\?|~)?\s*"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9 _-]*?)"
    r"\s*(?:[<>=]=?.*)?\Z"
)


class ModError(Exception):
    """Raised when a mod cannot be resolved or downloaded."""


def fetch_mod_info(name: str) -> dict:
    """Fetch the full mod-portal record for a mod (public, no auth)."""
    url = API_FULL.format(name=urllib.parse.quote(name))
    with net.urlopen(url, timeout=HTTP_TIMEOUT) as response:
        return json.load(response)


def select_release(info: dict, build_version: str, pinned: str | None) -> dict:
    """Choose the release to install for a mod.

    Pinned mods resolve to that exact version. Unpinned mods resolve to the
    newest release whose ``factorio_version`` matches the game build's
    ``major.minor``.

    :raises ModError: if no suitable release exists.
    """
    releases = info.get("releases", [])
    want = major_minor(build_version)
    if pinned is not None:
        for release in releases:
            if release["version"] == pinned:
                got = release.get("info_json", {}).get("factorio_version")
                if got and got != want:
                    print(
                        f"warning: {info.get('name')} {pinned} targets Factorio "
                        f"{got}, but this instance runs {want}; it may fail to load",
                        file=sys.stderr,
                    )
                return release
        raise ModError(f"{info.get('name')}: pinned version {pinned} not found")
    candidates = [
        release
        for release in releases
        if release.get("info_json", {}).get("factorio_version") == want
    ]
    if not candidates:
        raise ModError(
            f"{info.get('name')}: no release for Factorio {want}"
        )
    return max(candidates, key=lambda release: version_tuple(release["version"]))


def cache_path(mod: str, version: str) -> Path:
    """Path a mod version occupies in the cache."""
    return paths.mod_cache_dir(mod) / f"{mod}_{version}.zip"


def _metadata_path(mod: str) -> Path:
    """Sidecar recording the game version each cached release targets."""
    return paths.mod_cache_dir(mod) / "metadata.json"


def metadata(mod: str) -> dict:
    """Return ``{version: {"factorio_version", "sha1"}}`` for a cached mod."""
    path = _metadata_path(mod)
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("releases", {})


def factorio_version_of(mod: str, version: str) -> str | None:
    """Return the game ``major.minor`` a cached mod version was fetched for."""
    return metadata(mod).get(version, {}).get("factorio_version")


def _record_metadata(mod: str, release: dict) -> None:
    """Persist a cached release's game version and checksum (idempotent)."""
    game = release.get("info_json", {}).get("factorio_version")
    if game is None:
        return
    version = release["version"]
    releases = metadata(mod)
    if releases.get(version, {}).get("factorio_version") == game:
        return  # already recorded
    releases[version] = {"factorio_version": game, "sha1": release.get("sha1")}
    path = _metadata_path(mod)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"releases": releases}, indent=2) + "\n")


def ensure_cached(mod: str, release: dict, credentials: dict) -> Path:
    """Ensure a resolved release is present in the cache, downloading if not.

    Downloads to a ``.part`` file, verifies its SHA-1 against the portal's
    checksum, then atomically renames into place. A partial or corrupt download
    is discarded rather than cached. Existing cache files are never overwritten.
    The release's game version is recorded to the mod's metadata sidecar so the
    cache is self-describing (which zip targets which Factorio ``major.minor``).

    :raises ModError: if the download fails its checksum.
    """
    version = release["version"]
    target = cache_path(mod, version)
    if target.exists():
        _record_metadata(mod, release)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    query = urllib.parse.urlencode(
        {"username": credentials["username"], "token": credentials["token"]}
    )
    url = f"{API_BASE}{release['download_url']}?{query}"
    tmp = target.with_suffix(".zip.part")
    digest = hashlib.sha1()
    try:
        with net.urlopen(url, timeout=HTTP_TIMEOUT) as response, \
                tmp.open("wb") as out:
            while chunk := response.read(65536):
                digest.update(chunk)
                out.write(chunk)
        expected = release.get("sha1")
        if expected and digest.hexdigest() != expected:
            raise ModError(
                f"{mod} {version}: sha1 mismatch "
                f"(expected {expected}, got {digest.hexdigest()})"
            )
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    _record_metadata(mod, release)
    return target


def split_mod_filename(filename: str) -> tuple[str | None, str | None]:
    """Split a ``<mod>_<version>.zip`` name into ``(mod, version)``.

    Returns ``(None, None)`` for anything that is not a versioned mod zip.
    Mod names may contain underscores; the version never does (dotted digits),
    so splitting on the final underscore is unambiguous.
    """
    if not filename.endswith(".zip"):
        return None, None
    mod, sep, version = filename[: -len(".zip")].rpartition("_")
    if not sep or not version:
        return None, None
    if not all(part.isdigit() for part in version.split(".")):
        return None, None
    return mod, version


def _instance_links(mods_dir: Path, mod: str) -> list[Path]:
    """Return existing symlinks in an instance for a given mod."""
    links = []
    for link in mods_dir.glob("*.zip"):
        name, _ = split_mod_filename(link.name)
        if name == mod:
            links.append(link)
    return links


def link_into_instance(name: str, mod: str, version: str) -> Path:
    """Point an instance at a single cached version, dropping other links.

    Removes only this mod's stale symlinks (never cache files), then links the
    requested version so Factorio loads exactly that build.
    """
    mods_dir = paths.instance_mods(name)
    mods_dir.mkdir(parents=True, exist_ok=True)
    keep = cache_path(mod, version)
    link = mods_dir / keep.name
    for existing in _instance_links(mods_dir, mod):
        if existing != link:
            existing.unlink()
    if not link.exists():
        link.symlink_to(keep)
    return link


def write_mod_list(name: str, mod_names: list[str]) -> None:
    """Write ``mod-list.json`` enabling base plus the configured mods."""
    mods_dir = paths.instance_mods(name)
    mods_dir.mkdir(parents=True, exist_ok=True)
    enabled = ["base"] + [m for m in mod_names if m != "base"]
    data = {"mods": [{"name": mod, "enabled": True} for mod in enabled]}
    (mods_dir / "mod-list.json").write_text(json.dumps(data, indent=2) + "\n")


def required_dependencies(release: dict) -> list[str]:
    """Return the non-optional, non-builtin dependency names of a release."""
    required: list[str] = []
    for dep in release.get("info_json", {}).get("dependencies", []):
        match = _DEP_RE.match(dep)
        if not match:
            continue
        if match.group("prefix") in ("!", "?", "(?)"):
            continue  # incompatible or optional; not needed to boot
        name = match.group("name").strip()
        if name and name not in BUILTIN:
            required.append(name)
    return required


def resolve_closure(
    entries: list[dict], build_version: str
) -> dict[str, dict]:
    """Resolve entries plus their required dependencies to concrete releases.

    :param entries: mods to resolve (``{name, version?}``); builtins ignored.
    :returns: mapping of mod name to the chosen release, dependencies included.
    """
    resolved: dict[str, dict] = {}
    queue = [(e["name"], e.get("version")) for e in entries if e["name"] not in BUILTIN]
    seen: set[str] = set()
    while queue:
        mod, pinned = queue.pop(0)
        if mod in seen or mod in BUILTIN:
            continue
        seen.add(mod)
        release = select_release(fetch_mod_info(mod), build_version, pinned)
        resolved[mod] = release
        for dep in required_dependencies(release):
            if dep not in seen:
                queue.append((dep, None))  # dependencies track latest compatible
    return resolved


def _prune_links(name: str, keep: set[str]) -> None:
    """Remove instance mod symlinks whose mod is no longer configured.

    Only instance symlinks are removed; the cache is never touched.
    """
    mods_dir = paths.instance_mods(name)
    if not mods_dir.is_dir():
        return
    for link in mods_dir.glob("*.zip"):
        mod, _ = split_mod_filename(link.name)
        if mod is not None and mod not in keep:
            link.unlink()


def sync_instance(
    name: str,
    mods: list[dict],
    build_version: str,
    credentials: dict,
    *,
    unpinned_only: bool = False,
) -> list[tuple[str, str]]:
    """Resolve, cache and link every configured mod (and dependency).

    :param mods: the instance's ``mods`` list (dicts with ``name`` / optional
        ``version``).
    :param build_version: concrete game version driving mod compatibility.
    :param credentials: account credentials for downloads.
    :param unpinned_only: when true (the ``mods update`` pre-run path), only
        unpinned mods are re-resolved, ``mod-list.json`` is left untouched, and
        stale links are not pruned so pinned mods and manual toggles survive.
    :returns: list of ``(mod, version)`` tuples that were linked.
    """
    entries = [m for m in mods if m["name"] not in BUILTIN]
    if unpinned_only:
        entries = [m for m in entries if m.get("version") is None]
    resolved = resolve_closure(entries, build_version)

    linked: list[tuple[str, str]] = []
    for mod, release in resolved.items():
        version = release["version"]
        ensure_cached(mod, release, credentials)
        link_into_instance(name, mod, version)
        linked.append((mod, version))

    if not unpinned_only:
        configured = [m["name"] for m in mods]
        deps = [mod for mod in resolved if mod not in configured]
        write_mod_list(name, configured + deps)
        _prune_links(name, set(resolved))
    return linked


def download(
    name: str,
    game_version: str,
    credentials: dict,
    *,
    version: str | None = None,
) -> list[tuple[str, str]]:
    """Download a mod and its required dependencies into the cache.

    Instance-independent: nothing is linked, only cached. Existing cache files
    are kept; only missing versions are fetched.

    :param name: mod name.
    :param game_version: game version (concrete or ``major.minor``) to match.
    :param version: pin an exact version instead of the latest compatible.
    :returns: ``(mod, version)`` tuples now present in the cache.
    :raises ModError: if the mod or a dependency has no compatible release.
    """
    resolved = resolve_closure([{"name": name, "version": version}], game_version)
    cached: list[tuple[str, str]] = []
    for mod, release in resolved.items():
        ensure_cached(mod, release, credentials)
        cached.append((mod, release["version"]))
    return cached


def refresh(
    game_version: str,
    credentials: dict,
    *,
    extra_mods: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Add the latest compatible version of every known mod to the cache.

    The mod set is every already-cached mod plus ``extra_mods`` (e.g. mods
    configured in instances but not yet downloaded), with their dependencies.
    Best-effort and keep-forever: mods with no release for ``game_version`` are
    skipped rather than failing the run, and older cached versions are retained.

    :param extra_mods: additional mod names to include beyond the cache.
    :returns: ``(mod, version)`` tuples that were newly downloaded.
    """
    names = set(list_cached_mods())
    if extra_mods:
        names |= {mod for mod in extra_mods if mod not in BUILTIN}
    resolved: dict[str, dict] = {}
    for mod in sorted(names):
        try:
            closure = resolve_closure([{"name": mod}], game_version)
        except (ModError, OSError):
            continue  # no compatible release (or transient portal error); skip
        for dep, release in closure.items():
            resolved.setdefault(dep, release)
    added: list[tuple[str, str]] = []
    for mod, release in resolved.items():
        was_present = cache_path(mod, release["version"]).exists()
        ensure_cached(mod, release, credentials)
        if not was_present:
            added.append((mod, release["version"]))
    return added


def describe(name: str, game_versions: list[str]) -> dict:
    """Summarize a mod: latest, the pick per game version, deps, cache state.

    :param game_versions: game versions (concrete or ``major.minor``) to resolve
        picks for; a version with no compatible release maps to ``None``.
    :returns: mapping with ``picks`` (``{game_version: chosen_version|None}``)
        and ``cached`` tagged with each version's recorded game version.
    :raises ModError: never for compatibility; portal/network errors propagate.
    """
    info = fetch_mod_info(name)
    all_versions = sorted(
        (r["version"] for r in info.get("releases", [])),
        key=version_tuple,
        reverse=True,
    )
    picks: dict[str, str | None] = {}
    primary = None
    for game_version in game_versions:
        try:
            chosen = select_release(info, game_version, None)
        except ModError:
            picks[game_version] = None
            continue
        picks[game_version] = chosen["version"]
        primary = primary or chosen
    meta = metadata(name)
    cached = cached_versions(name)
    return {
        "name": info.get("name", name),
        "title": info.get("title", ""),
        "latest": all_versions[0] if all_versions else None,
        "picks": picks,
        "dependencies": required_dependencies(primary) if primary else [],
        "cached": cached,
        "cached_game_versions": {
            version: meta.get(version, {}).get("factorio_version") for version in cached
        },
    }


def cached_versions(mod: str) -> list[str]:
    """Return every cached version of a mod, newest first."""
    cache_dir = paths.mod_cache_dir(mod)
    if not cache_dir.is_dir():
        return []
    versions = []
    for path in cache_dir.glob("*.zip"):
        name, version = split_mod_filename(path.name)
        if name == mod and version is not None:
            versions.append(version)
    return sorted(versions, key=version_tuple, reverse=True)


def list_cached_mods() -> dict[str, list[str]]:
    """Map every cached mod to its cached versions (newest first)."""
    cache = paths.mods_cache()
    if not cache.is_dir():
        return {}
    return {
        child.name: cached_versions(child.name)
        for child in sorted(cache.iterdir())
        if child.is_dir()
    }
