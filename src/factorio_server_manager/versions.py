"""Reporting for ``fsm show versions``.

Summarizes the local pools (installed game builds and cached mod versions and
which version each instance links) and, with ``available=True``, the latest
versions published on factorio.com and the mod portal.
"""

from __future__ import annotations

from . import binary, instance, mods, paths
from .semver import latest


def _instance_mod_links() -> dict[str, dict[str, str]]:
    """Map each instance to the mod versions it currently links."""
    result: dict[str, dict[str, str]] = {}
    root = paths.instances_dir()
    if not root.is_dir():
        return result
    for child in sorted(root.iterdir()):
        if not (child / "instance.yaml").exists():
            continue
        links: dict[str, str] = {}
        mods_dir = child / "mods"
        if mods_dir.is_dir():
            for link in sorted(mods_dir.glob("*.zip")):
                mod, version = mods.split_mod_filename(link.name)
                if mod is not None:
                    links[mod] = version
        result[child.name] = links
    return result


def collect(available: bool = False) -> dict:
    """Gather a version report.

    :param available: also query the portals for the newest published versions.
    :returns: a mapping suitable for :func:`render`.
    """
    report = {
        "game": {
            "installed": binary.installed_versions(),
            "current": binary.current_version(),
            "channels": binary.channels(),
        },
        "mods": {
            "cached": mods.list_cached_mods(),
            "instances": _instance_mod_links(),
        },
    }
    if available:
        try:
            report["game"]["available"] = binary.latest_releases()
        except (OSError, ValueError) as exc:
            report["game"]["available"] = {"error": str(exc)}
        report["mods"]["available"] = _mod_latest_available(report["mods"]["cached"])
    return report


def _mod_latest_available(cached: dict) -> dict:
    """Query the portal for the newest release of every cached/configured mod."""
    names = set(cached) | instance.configured_mod_names()
    result: dict[str, str] = {}
    for name in sorted(names):
        try:
            info = mods.fetch_mod_info(name)
            versions = [r["version"] for r in info.get("releases", [])]
            result[name] = latest(versions) or ""
        except (OSError, ValueError) as exc:
            result[name] = f"error: {exc}"
    return result


def _format_game_available(available: dict) -> str:
    """Render the latest-releases payload as ``stable X, experimental Y``."""
    if "error" in available:
        return f"(error: {available['error']})"
    parts = []
    for channel in ("stable", "experimental"):
        headless = available.get(channel, {}).get("headless")
        if headless:
            parts.append(f"{channel} {headless}")
    return ", ".join(parts) if parts else "(unknown)"


def render(report: dict) -> str:
    """Format a version report as human-readable text."""
    lines: list[str] = []
    game = report["game"]
    channels_by_version: dict[str, list[str]] = {}
    for channel, version in game.get("channels", {}).items():
        channels_by_version.setdefault(version, []).append(channel)
    lines.append("Game builds (pool):")
    for version in game["installed"] or ["(none installed)"]:
        tags = channels_by_version.get(version, [])
        suffix = f"  ({', '.join(tags)})" if tags else ""
        lines.append(f"    {version}{suffix}")
    if "available" in game:
        lines.append(f"    latest available: {_format_game_available(game['available'])}")

    lines.append("")
    lines.append("Cached mods:")
    cached = report["mods"]["cached"]
    if not cached:
        lines.append("    (none cached)")
    for mod, versions in cached.items():
        avail = report["mods"].get("available", {}).get(mod)
        suffix = f"  (latest: {avail})" if avail else ""
        lines.append(f"    {mod}: {', '.join(versions)}{suffix}")

    lines.append("")
    lines.append("Instance mod links:")
    instances = report["mods"]["instances"]
    if not instances:
        lines.append("    (no instances)")
    for name, links in instances.items():
        if links:
            joined = ", ".join(f"{m}={v}" for m, v in links.items())
        else:
            joined = "(none)"
        lines.append(f"    {name}: {joined}")
    return "\n".join(lines)
