"""Command-line entry point for the ``fsm`` console script.

Argparse-based dispatch, run on the server. Subcommands cover the game version
pool (``binary``), instance lifecycle (``instance``), the mod pool (``mods``),
version reporting (``show``), the systemd units (``systemd``), the service entry
point (``run``), instance control (start/stop/...), live ops (``rcon``,
``backup``), and health checks (``doctor``).
"""

from __future__ import annotations

import argparse
import sys

from . import (
    __version__,
    binary,
    config,
    control,
    doctor,
    instance,
    mods,
    paths,
    rcon,
    server,
    systemd,
    versions,
)
from .semver import major_minor


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="fsm", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--version", action="version", version=f"fsm {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    _add_binary(sub)
    _add_instance(sub)
    _add_mods(sub)
    _add_show(sub)
    _add_systemd(sub)
    _add_run(sub)
    _add_control(sub)
    _add_rcon(sub)
    _add_backup(sub)
    _add_doctor(sub)
    return parser


def _add_binary(sub) -> None:
    binary_p = sub.add_parser("binary", help="manage the game version pool")
    binary_sub = binary_p.add_subparsers(dest="action", required=True)
    install = binary_sub.add_parser("install", help="download and extract a build")
    install.add_argument(
        "--version",
        default="stable",
        help="'stable', 'experimental' (alias 'latest'), or a concrete version like 2.1.9",
    )
    install.add_argument("--make-current", action="store_true", help="point 'current' at it")
    install.set_defaults(func=_cmd_binary_install)
    make_current = binary_sub.add_parser("current", help="set the current build")
    make_current.add_argument("version")
    make_current.set_defaults(func=_cmd_binary_current)
    update = binary_sub.add_parser(
        "update", help="refresh opted-in channels (stable/experimental) to latest"
    )
    update.set_defaults(func=_cmd_binary_update)
    list_p = binary_sub.add_parser("list", help="list installed builds")
    list_p.set_defaults(func=_cmd_binary_list)


def _add_instance(sub) -> None:
    inst_p = sub.add_parser("instance", help="assemble and list instances")
    inst_sub = inst_p.add_subparsers(dest="action", required=True)
    new = inst_sub.add_parser("new", help="scaffold a new instance.yaml")
    new.add_argument("name")
    new.add_argument("--port", type=int, help="UDP port (default: next free)")
    new.set_defaults(func=_cmd_instance_new)
    assemble = inst_sub.add_parser("assemble", help="materialize from instance.yaml")
    assemble.add_argument("name")
    assemble.set_defaults(func=_cmd_instance_assemble)
    remove = inst_sub.add_parser(
        "remove", help="stop, disable and delete an instance (and its saves)"
    )
    remove.add_argument("name")
    remove.add_argument(
        "--force", action="store_true", help="required: confirms deleting saves"
    )
    remove.set_defaults(func=_cmd_instance_remove)
    create_map = inst_sub.add_parser(
        "create-map", help="generate a fresh world from the instance's map settings"
    )
    create_map.add_argument("name")
    create_map.add_argument("--force", action="store_true", help="overwrite an existing save")
    create_map.add_argument("--seed", type=int, help="override the map generation seed")
    create_map.set_defaults(func=_cmd_instance_create_map)
    list_p = inst_sub.add_parser("list", help="list configured instances")
    list_p.set_defaults(func=_cmd_instance_list)


def _add_mods(sub) -> None:
    mods_p = sub.add_parser("mods", help="manage the mod pool")
    mods_sub = mods_p.add_subparsers(dest="action", required=True)

    update = mods_sub.add_parser("update", help="refresh an instance's unpinned mods")
    update.add_argument("--instance", required=True)
    update.set_defaults(func=_cmd_mods_update)

    gv_help = "game version to match: concrete, major.minor, or 'all' (default: current)"
    download = mods_sub.add_parser(
        "download", help="cache a mod (and its dependencies), no instance needed"
    )
    download.add_argument("name")
    download.add_argument("--version", help="pin an exact version (default: latest)")
    download.add_argument("--game-version", help=gv_help)
    download.set_defaults(func=_cmd_mods_download)

    refresh = mods_sub.add_parser(
        "refresh", help="cache the latest version of every already-cached mod"
    )
    refresh.add_argument("--game-version", help=gv_help)
    refresh.set_defaults(func=_cmd_mods_refresh)

    info = mods_sub.add_parser("info", help="show a mod's releases and cache state")
    info.add_argument("name")
    info.add_argument("--game-version", help=gv_help)
    info.set_defaults(func=_cmd_mods_info)

    list_p = mods_sub.add_parser("list", help="list cached mods and versions")
    list_p.set_defaults(func=_cmd_mods_list)


def _add_show(sub) -> None:
    show_p = sub.add_parser("show", help="report state")
    show_sub = show_p.add_subparsers(dest="action", required=True)
    version_p = show_sub.add_parser("versions", help="game builds and mod versions")
    version_p.add_argument(
        "--available", action="store_true", help="also query the portals for latest"
    )
    version_p.set_defaults(func=_cmd_show_versions)


def _add_systemd(sub) -> None:
    sysd_p = sub.add_parser("systemd", help="manage the systemd units")
    sysd_sub = sysd_p.add_subparsers(dest="action", required=True)
    install = sysd_sub.add_parser("install", help="install the user template unit")
    install.set_defaults(func=_cmd_systemd_install)
    timers = sysd_sub.add_parser(
        "install-timers", help="install + enable the maintenance timers"
    )
    timers.set_defaults(func=_cmd_systemd_install_timers)


def _add_doctor(sub) -> None:
    doctor_p = sub.add_parser("doctor", help="run preflight health checks")
    doctor_p.add_argument(
        "--online", action="store_true", help="also check factorio.com connectivity"
    )
    doctor_p.set_defaults(func=_cmd_doctor)


def _add_run(sub) -> None:
    run_p = sub.add_parser("run", help="launch an instance (systemd ExecStart)")
    run_p.add_argument("name")
    run_p.set_defaults(func=_cmd_run)


def _add_control(sub) -> None:
    for name, help_text in (
        ("start", "start an instance"),
        ("stop", "stop an instance"),
        ("enable", "enable an instance on boot"),
        ("disable", "disable an instance on boot"),
        ("status", "show unit status"),
    ):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("name")
        parser.set_defaults(func=_make_control(name))
    logs_p = sub.add_parser("logs", help="show an instance's journal")
    logs_p.add_argument("name")
    logs_p.add_argument("-f", "--follow", action="store_true")
    logs_p.set_defaults(func=_cmd_logs)


def _add_rcon(sub) -> None:
    rcon_p = sub.add_parser("rcon", help="run a console command on a live instance")
    rcon_p.add_argument("name")
    rcon_p.add_argument("command", nargs="+", help="console command, e.g. /players")
    rcon_p.set_defaults(func=_cmd_rcon)


def _add_backup(sub) -> None:
    backup_p = sub.add_parser("backup", help="snapshot an instance's newest save")
    backup_p.add_argument("name")
    backup_p.add_argument(
        "--keep", type=int, default=10, help="number of backups to retain (default: 10)"
    )
    backup_p.set_defaults(func=_cmd_backup)


def _cmd_binary_install(args) -> int:
    version = binary.install(args.version, make_current=args.make_current)
    print(f"installed factorio {version}")
    return 0


def _cmd_binary_current(args) -> int:
    binary.set_current(args.version)
    print(f"current -> {args.version}")
    return 0


def _cmd_binary_update(args) -> int:
    changes = binary.update()
    if not changes:
        print("channels already up to date")
    for channel, old, new in changes:
        print(f"{channel}: {old or '(none)'} -> {new}")
    return 0


def _cmd_binary_list(args) -> int:
    channels_by_version: dict[str, list[str]] = {}
    for channel, version in binary.channels().items():
        channels_by_version.setdefault(version, []).append(channel)
    for version in binary.installed_versions():
        tags = channels_by_version.get(version, [])
        suffix = f"  ({', '.join(tags)})" if tags else ""
        print(f"  {version}{suffix}")
    return 0


def _cmd_instance_assemble(args) -> int:
    summary = instance.assemble(args.name)
    linked = ", ".join(f"{m}={v}" for m, v in summary["mods"]) or "none"
    print(
        f"assembled {args.name}: factorio {summary['version']}, "
        f"port {summary['port']}, mods: {linked}"
    )
    return 0


def _cmd_instance_new(args) -> int:
    path, port = instance.new(args.name, port=args.port)
    print(f"created {path} (port {port}); edit it, then 'fsm instance assemble {args.name}'")
    return 0


def _cmd_instance_remove(args) -> int:
    if not args.force:
        print(
            f"refusing to remove '{args.name}' without --force "
            "(this deletes the instance and its saves)",
            file=sys.stderr,
        )
        return 1
    instance.remove(args.name)
    print(f"removed {args.name}")
    return 0


def _cmd_instance_create_map(args) -> int:
    save = instance.create_map(args.name, force=args.force, seed=args.seed)
    print(f"created map: {save}")
    return 0


def _cmd_instance_list(args) -> int:
    for name in instance.list_instances():
        print(name)
    return 0


def _cmd_mods_update(args) -> int:
    linked = instance.update_mods(args.instance)
    for mod, version in linked:
        print(f"{mod} -> {version}")
    return 0


def _resolve_game_version(explicit: str | None) -> str:
    """Return a single game version to match: explicit, else the current build."""
    if explicit:
        return explicit
    current = binary.current_version()
    if not current:
        raise ValueError("no current build; install one or pass --game-version")
    return current


def _game_version_targets(explicit: str | None) -> list[str]:
    """Expand a ``--game-version`` value into the versions to act on.

    ``all`` expands to the stable and experimental channel game versions
    (deduplicated by ``major.minor``); anything else is a single target.
    """
    if explicit == "all":
        channels = binary.channel_game_versions()
        if not channels:
            raise ValueError("could not determine stable/experimental game versions")
        targets: list[str] = []
        seen: set[str] = set()
        for channel in ("stable", "experimental"):
            version = channels.get(channel)
            if version and major_minor(version) not in seen:
                seen.add(major_minor(version))
                targets.append(version)
        return targets
    return [_resolve_game_version(explicit)]


def _cmd_mods_download(args) -> int:
    credentials = config.load_credentials()
    cached: list[tuple[str, str]] = []
    for game_version in _game_version_targets(args.game_version):
        for entry in mods.download(
            args.name, game_version, credentials, version=args.version
        ):
            if entry not in cached:
                cached.append(entry)
    for mod, version in cached:
        game = mods.factorio_version_of(mod, version)
        tag = f" (factorio {game})" if game else ""
        print(f"{mod} {version}{tag}")
    return 0


def _cmd_mods_refresh(args) -> int:
    extra = instance.configured_mod_names()
    if not mods.list_cached_mods() and not extra:
        print("no mods to refresh (cache empty, no instances configured)")
        return 0
    credentials = config.load_credentials()
    added: list[tuple[str, str]] = []
    for game_version in _game_version_targets(args.game_version):
        for entry in mods.refresh(game_version, credentials, extra_mods=extra):
            if entry not in added:
                added.append(entry)
    if not added:
        print("cache already up to date")
    for mod, version in added:
        game = mods.factorio_version_of(mod, version)
        tag = f" (factorio {game})" if game else ""
        print(f"+ {mod} {version}{tag}")
    return 0


def _cmd_mods_info(args) -> int:
    targets = _game_version_targets(args.game_version)
    summary = mods.describe(args.name, targets)
    print(f"{summary['name']}  {summary['title']}".rstrip())
    print(f"  latest:       {summary['latest'] or '(none)'}")
    for game_version, version in summary["picks"].items():
        print(f"  for {game_version}: {version or '(no compatible release)'}")
    if summary["dependencies"]:
        print(f"  dependencies: {', '.join(summary['dependencies'])}")
    tags = summary["cached_game_versions"]
    cached = [
        f"{v} ({tags[v]})" if tags.get(v) else v for v in summary["cached"]
    ]
    print(f"  cached:       {', '.join(cached) or '(none)'}")
    return 0


def _cmd_mods_list(args) -> int:
    for mod, mod_versions in mods.list_cached_mods().items():
        meta = mods.metadata(mod)
        tagged = [
            f"{v} ({meta[v]['factorio_version']})" if v in meta else v
            for v in mod_versions
        ]
        print(f"{mod}: {', '.join(tagged)}")
    return 0


def _cmd_show_versions(args) -> int:
    print(versions.render(versions.collect(available=args.available)))
    return 0


def _cmd_systemd_install(args) -> int:
    target = systemd.install()
    print(f"installed {target}")
    return 0


def _cmd_systemd_install_timers(args) -> int:
    for target in systemd.install_timers():
        print(f"installed {target}")
    print("enabled maintenance timers")
    return 0


def _cmd_doctor(args) -> int:
    results = doctor.run(online=args.online)
    print(doctor.render(results))
    return 1 if any(r.status == "fail" for r in results) else 0


def _cmd_run(args) -> int:
    server.run(args.name)  # replaces this process; returns only on failure
    return 0


def _make_control(action: str):
    """Build a control command handler for a systemctl verb."""
    def handler(args) -> int:
        paths.validate_name(args.name)
        return getattr(control, action)(args.name)
    return handler


def _cmd_logs(args) -> int:
    paths.validate_name(args.name)
    return control.logs(args.name, follow=args.follow)


def _cmd_rcon(args) -> int:
    paths.validate_name(args.name)
    host, port, password = rcon.instance_endpoint(args.name)
    output = rcon.execute(host, port, password, " ".join(args.command))
    if output:
        print(output)
    return 0


def _cmd_backup(args) -> int:
    dest, removed = instance.backup(args.name, keep=args.keep)
    print(f"backup: {dest}")
    for path in removed:
        print(f"rotated out: {path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - surface a clean message, non-zero exit
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
