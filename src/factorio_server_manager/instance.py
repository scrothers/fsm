"""Assembly of an instance's runtime directory from its ``instance.yaml``.

``assemble`` is idempotent: it regenerates the derived files (``config.ini``,
``server-settings.json``, ``server-adminlist.json``, ``instance.json``,
``mod-list.json``), resolves and links mods from the cache, and seeds the
default world only when no save exists yet. It never clobbers an existing save.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

from . import config, control, mods, paths, systemd


class InstanceError(Exception):
    """Raised when an instance operation (create, remove, map, backup) fails."""


#: Starter written by ``instance new`` (a minimal, working config).
_NEW_INSTANCE_TEMPLATE = """\
# Instance config. See the annotated reference at
# src/factorio_server_manager/templates/instance.yaml.example for every option.
game_version: current
port: {port}
save: world.zip

server_settings:
  name: "{name}"
  visibility: {{ public: false, lan: true }}
  game_password: ""
  max_players: 0
  admins: []

mods: []

performance:
  non_blocking_saving: true
"""


#: Map ``performance:`` YAML keys to the systemd ``[Service]`` directive they set.
_PERF_DIRECTIVES = {
    "cpu_affinity": "CPUAffinity",
    "nice": "Nice",
    "cpu_weight": "CPUWeight",
    "io_weight": "IOWeight",
    "memory_high": "MemoryHigh",
    "memory_max": "MemoryMax",
}

#: Baseline multiplayer server settings; overlaid by the YAML block.
DEFAULT_SERVER_SETTINGS = {
    "name": "Factorio",
    "description": "",
    "tags": [],
    "max_players": 0,
    "visibility": {"public": False, "lan": True},
    "game_password": "",
    "require_user_verification": True,
    "max_upload_in_kilobytes_per_second": 0,
    "max_upload_slots": 5,
    "allow_commands": "admins-only",
    "autosave_interval": 10,
    "autosave_slots": 5,
    "afk_autokick_interval": 0,
    "auto_pause": True,
    "only_admins_can_pause_the_game": True,
    "autosave_only_on_server": True,
}


def assemble(name: str) -> dict:
    """Materialize an instance directory from its authored config.

    :param name: instance name.
    :returns: a summary mapping (resolved version, port, linked mods).
    """
    cfg = config.load_instance(name)
    build_version = config.resolve_build(cfg["game_version"])
    credentials = _credentials_for(cfg)
    _warn_port_conflicts(name, cfg["port"])

    _make_dirs(name)
    _write_config_ini(name, build_version, cfg)
    _write_server_settings(name, cfg, credentials)
    _write_admin_list(name, cfg)
    _write_access_lists(name, cfg)
    _write_runtime(name, cfg, build_version)
    _apply_performance(name, cfg)
    linked = mods.sync_instance(
        name, cfg["mods"], build_version, credentials
    )
    _seed_world(name, cfg["save"])
    return {"version": build_version, "port": cfg["port"], "mods": linked}


def _apply_performance(name: str, cfg: dict) -> None:
    """Render the instance's systemd resource drop-in (or clear a stale one)."""
    perf = cfg.get("performance") or {}
    directives = {
        directive: str(perf[key])
        for key, directive in _PERF_DIRECTIVES.items()
        if perf.get(key) is not None
    }
    # Only touch systemd when there is something to set or a stale drop-in to clear.
    if directives or systemd.instance_dropin(name).exists():
        systemd.apply_dropin(name, directives)


def _credentials_for(cfg: dict) -> dict:
    """Load account credentials only when mods or public listing need them.

    A vanilla, non-public instance can be assembled without a secrets file.
    """
    has_mods = any(m["name"] not in mods.BUILTIN for m in cfg["mods"])
    public = bool(cfg.get("server_settings", {}).get("visibility", {}).get("public"))
    if has_mods or public:
        return config.load_credentials()
    return {"username": "", "token": ""}


def _warn_port_conflicts(name: str, port: int) -> None:
    """Warn (without failing) if another instance is configured on this port."""
    for other in list_instances():
        if other == name:
            continue
        try:
            other_cfg = config.load_instance(other)
        except config.ConfigError:
            continue
        if other_cfg["port"] == port:
            print(
                f"warning: instance '{other}' also uses UDP port {port}",
                file=sys.stderr,
            )


def update_mods(name: str) -> list[tuple[str, str]]:
    """Refresh an instance's unpinned mods (the ``ExecStartPre`` path).

    Pinned mods are left untouched; unpinned mods are re-resolved to the latest
    compatible release, cached if new, and relinked.

    :returns: list of ``(mod, version)`` tuples now linked.
    """
    cfg = config.load_instance(name)
    build_version = config.resolve_build(cfg["game_version"])
    credentials = config.load_credentials()
    return mods.sync_instance(
        name, cfg["mods"], build_version, credentials, unpinned_only=True
    )


def _make_dirs(name: str) -> None:
    """Create the instance's subdirectories."""
    paths.instance_saves(name).mkdir(parents=True, exist_ok=True)
    paths.instance_mods(name).mkdir(parents=True, exist_ok=True)


def _non_blocking_saving(cfg: dict) -> bool:
    """Whether forked (background/non-blocking) autosaving is enabled."""
    return bool((cfg.get("performance") or {}).get("non_blocking_saving", True))


def _write_config_ini(name: str, build_version: str, cfg: dict) -> None:
    """Write the isolation config and any extra ``config.ini`` settings.

    ``[path]`` gives the shared read-data / instance-local write-data isolation.
    Non-blocking (forked) autosaving is enabled by default so autosaves do not
    stall the simulation; set ``performance.non_blocking_saving: false`` to opt
    out. A top-level ``config_ini:`` mapping of section -> {key: value} is merged
    on top, so any engine setting (threading-related or otherwise) is reachable.
    """
    build = paths.build_dir(build_version)
    sections: dict[str, dict[str, str]] = {
        "path": {
            "read-data": str(paths.data_dir(build)),
            "write-data": str(paths.instance_dir(name)),
        }
    }
    if _non_blocking_saving(cfg):
        sections.setdefault("other", {})["non-blocking-saving"] = "true"
    for section, keys in (cfg.get("config_ini") or {}).items():
        target = sections.setdefault(section, {})
        for key, value in keys.items():
            target[key] = _ini_value(value)
    _write_ini(paths.instance_dir(name) / "config.ini", sections)


def _ini_value(value) -> str:
    """Render a scalar as a config.ini value (bools as lowercase true/false)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_ini(path, sections: dict) -> None:
    """Write an INI file from an ordered mapping of section -> {key: value}."""
    lines = ["; Generated by fsm. Edit instance.yaml and re-assemble instead."]
    for section, keys in sections.items():
        if not keys:
            continue
        lines.append(f"[{section}]")
        lines.extend(f"{key}={value}" for key, value in keys.items())
        lines.append("")
    path.write_text("\n".join(lines).rstrip("\n") + "\n")


def _write_server_settings(name: str, cfg: dict, credentials: dict) -> None:
    """Render ``server-settings.json`` from defaults + YAML + credentials."""
    settings = json.loads(json.dumps(DEFAULT_SERVER_SETTINGS))  # deep copy
    overlay = dict(cfg.get("server_settings", {}))
    overlay.pop("admins", None)  # admins live in server-adminlist.json
    _deep_update(settings, overlay)
    settings["username"] = credentials["username"]
    settings["token"] = credentials["token"]
    # Written to both surfaces (server-settings.json and config.ini) so the
    # background/non-blocking save is honored regardless of which the engine reads.
    settings["non_blocking_saving"] = _non_blocking_saving(cfg)
    path = paths.instance_dir(name) / "server-settings.json"
    _write_private(path, json.dumps(settings, indent=2) + "\n")


def _write_admin_list(name: str, cfg: dict) -> None:
    """Write ``server-adminlist.json`` from the configured admins."""
    admins = cfg.get("server_settings", {}).get("admins", [])
    _write_json_list(paths.instance_dir(name) / "server-adminlist.json", admins)


def _write_access_lists(name: str, cfg: dict) -> None:
    """Write the whitelist / banlist files when configured (non-empty)."""
    inst = paths.instance_dir(name)
    for field, filename in (
        ("whitelist", "server-whitelist.json"),
        ("banlist", "server-banlist.json"),
    ):
        items = cfg.get(field) or []
        if items:
            _write_json_list(inst / filename, items)


def _write_json_list(path, items: list) -> None:
    """Write a JSON array file (adminlist/whitelist/banlist)."""
    path.write_text(json.dumps(items, indent=2) + "\n")


def _write_runtime(name: str, cfg: dict, build_version: str) -> None:
    """Write ``instance.json`` runtime facts consumed by ``fsm run``."""
    runtime = {
        "name": name,
        "game_version": build_version,
        "port": cfg["port"],
        "save": cfg["save"],
        "rcon": cfg.get("rcon"),
        "whitelist": bool(cfg.get("whitelist")),
        "banlist": bool(cfg.get("banlist")),
        "extra_args": cfg.get("extra_args", []),
    }
    _write_private(paths.instance_runtime(name), json.dumps(runtime, indent=2) + "\n")


def _write_private(path, text: str) -> None:
    """Write a file containing secrets with owner-only (0600) permissions."""
    path.write_text(text)
    os.chmod(path, 0o600)


def _seed_world(name: str, save: str) -> None:
    """Copy the default world into the instance only if no save exists."""
    target = paths.instance_saves(name) / save
    if target.exists():
        return
    default = paths.default_world()
    if default.exists():
        shutil.copy2(default, target)


def _deep_update(base: dict, overlay: dict) -> None:
    """Recursively merge ``overlay`` into ``base`` in place."""
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def list_instances() -> list[str]:
    """Return the names of all configured instances."""
    root = paths.instances_dir()
    if not root.is_dir():
        return []
    return sorted(
        child.name
        for child in root.iterdir()
        if (child / "instance.yaml").exists()
    )


def create_map(name: str, *, force: bool = False, seed: int | None = None):
    """Generate a fresh world for an instance from its map settings.

    Requires the instance to have been assembled (its ``config.ini`` provides
    the data and path layout). Map generation settings and map settings come
    from the optional ``map_gen_settings`` / ``map_settings`` YAML blocks; the
    seed comes from ``--seed``, else the ``seed`` YAML key. Mods are loaded if
    present so mod-driven map generation applies.

    :returns: the created save path.
    :raises InstanceError: if the binary/config is missing or the save exists.
    """
    cfg = config.load_instance(name)
    build_version = config.resolve_build(cfg["game_version"])
    binary = paths.binary_path(paths.build_dir(build_version))
    if not binary.exists():
        raise InstanceError(f"binary missing for version {build_version}: {binary}")
    inst = paths.instance_dir(name)
    config_ini = inst / "config.ini"
    if not config_ini.exists():
        raise InstanceError(f"assemble the instance first: fsm instance assemble {name}")
    save = paths.instance_saves(name) / cfg["save"]
    if save.exists() and not force:
        raise InstanceError(f"save already exists: {save} (use --force to overwrite)")
    paths.instance_saves(name).mkdir(parents=True, exist_ok=True)

    argv = [str(binary), "--create", str(save), "--config", str(config_ini)]
    if cfg.get("map_gen_settings"):
        path = inst / "map-gen-settings.json"
        path.write_text(json.dumps(cfg["map_gen_settings"], indent=2) + "\n")
        argv += ["--map-gen-settings", str(path)]
    if cfg.get("map_settings"):
        path = inst / "map-settings.json"
        path.write_text(json.dumps(cfg["map_settings"], indent=2) + "\n")
        argv += ["--map-settings", str(path)]
    chosen_seed = seed if seed is not None else cfg.get("seed")
    if chosen_seed is not None:
        argv += ["--map-gen-seed", str(chosen_seed)]
    if any(paths.instance_mods(name).glob("*.zip")):
        argv += ["--mod-directory", str(paths.instance_mods(name))]

    result = subprocess.run(argv, check=False)
    if result.returncode != 0:
        raise InstanceError(f"map creation failed (exit {result.returncode})")
    return save


def backup(name: str, *, keep: int = 10):
    """Snapshot the newest save into a rotated ``backups/`` directory.

    The most recently modified save (which may be an autosave) is copied to
    ``instances/<name>/backups/<save>_<timestamp>.zip``; the ``keep`` newest
    backups are retained and older ones removed.

    :returns: ``(backup_path, removed_paths)``.
    :raises InstanceError: if there is no save to back up.
    """
    saves = paths.instance_saves(name)
    zips = list(saves.glob("*.zip")) if saves.is_dir() else []
    if not zips:
        raise InstanceError(f"no save to back up in {saves}")
    newest = max(zips, key=lambda path: path.stat().st_mtime)
    backups = paths.instance_dir(name) / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(newest.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
    dest = backups / f"{newest.stem}_{stamp}.zip"
    shutil.copy2(newest, dest)
    return dest, _rotate_backups(backups, keep)


def _rotate_backups(backups, keep: int) -> list:
    """Keep the ``keep`` newest backups, removing older ones."""
    files = sorted(backups.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    removed = []
    if keep > 0 and len(files) > keep:
        for old in files[:-keep]:
            old.unlink()
            removed.append(old)
    return removed


def new(name: str, port: int | None = None):
    """Scaffold a new instance's ``instance.yaml`` from the starter template.

    :param port: UDP port; defaults to the next free port after existing ones.
    :returns: ``(path, port)``.
    :raises InstanceError: if the instance already exists or the port is in use.
    """
    paths.validate_name(name)
    config_path = paths.instance_config(name)
    if config_path.exists():
        raise InstanceError(f"instance already exists: {config_path}")
    if port is None:
        port = _next_free_port()
    elif port in _used_ports():
        raise InstanceError(f"port {port} is already used by another instance")
    paths.instance_dir(name).mkdir(parents=True, exist_ok=True)
    config_path.write_text(_NEW_INSTANCE_TEMPLATE.format(name=name, port=port))
    return config_path, port


def _used_ports() -> set[int]:
    """Ports currently claimed by configured instances."""
    ports = set()
    for other in list_instances():
        try:
            ports.add(config.load_instance(other)["port"])
        except config.ConfigError:
            continue
    return ports


def _next_free_port(base: int = 34197) -> int:
    """Return the lowest unused UDP port at or above ``base``."""
    used = _used_ports()
    port = base
    while port in used:
        port += 1
    return port


def remove(name: str) -> None:
    """Stop, disable and delete an instance and its systemd drop-in.

    Destructive: removes the instance directory including its saves. Callers
    should require explicit confirmation (the CLI requires ``--force``).

    :raises InstanceError: if the instance does not exist.
    """
    paths.validate_name(name)
    inst = paths.instance_dir(name)
    if not inst.exists():
        raise InstanceError(f"no such instance: {name}")
    for action in (control.stop, control.disable):
        try:
            action(name)  # best-effort: the unit may not be running/enabled
        except OSError:
            pass  # systemctl absent or unit missing
    systemd.remove_dropin(name)
    shutil.rmtree(inst)


def configured_mod_names() -> set[str]:
    """Return every non-builtin mod name referenced by any instance's YAML."""
    names: set[str] = set()
    for name in list_instances():
        try:
            cfg = config.load_instance(name)
        except config.ConfigError:
            continue
        for entry in cfg.get("mods", []):
            if entry.get("name") not in mods.BUILTIN:
                names.add(entry["name"])
    return names
