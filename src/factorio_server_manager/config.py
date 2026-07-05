"""Loading and resolution of instance configuration.

The authored ``instance.yaml`` is the source of truth. This module loads it,
resolves the requested game build to a concrete version in the pool, and reads
the account credentials used for authenticated mod downloads.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from . import paths


class ConfigError(Exception):
    """Raised when instance configuration or credentials are invalid."""


def load_instance(name: str) -> dict:
    """Load and lightly validate an instance's ``instance.yaml``.

    :param name: instance name (its directory under ``instances/``).
    :returns: the parsed configuration mapping.
    :raises ConfigError: if the file is missing or malformed.
    """
    try:
        paths.validate_name(name)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    path = paths.instance_config(name)
    if not path.exists():
        raise ConfigError(f"no instance config: {path}")
    with path.open() as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigError(f"instance config is not a mapping: {path}")
    data["name"] = name  # directory is authoritative; ignore any YAML 'name'
    data.setdefault("game_version", "current")
    data.setdefault("port", 34197)
    data.setdefault("save", "world.zip")
    data.setdefault("mods", [])
    data.setdefault("server_settings", {})
    # YAML numeric scalars (e.g. 2.0) must not silently become floats; a version
    # is always a string and a port is always an int.
    data["game_version"] = str(data["game_version"])
    if not isinstance(data["mods"], list):
        raise ConfigError("'mods' must be a list")
    _validate_port(data["port"])
    _validate_rcon(data.get("rcon"))
    for field in ("whitelist", "banlist", "extra_args"):
        _validate_str_list(data.get(field), field)
    for field in ("map_gen_settings", "map_settings"):
        _validate_mapping(data.get(field), field)
    if data.get("seed") is not None and not isinstance(data["seed"], int):
        raise ConfigError("'seed' must be an integer")
    _validate_performance(data.get("performance"))
    _validate_config_ini(data.get("config_ini"))
    return data


def _validate_config_ini(value: object) -> None:
    """Validate the optional ``config_ini`` passthrough (sections of scalars).

    Section names, keys and values are checked so a stray newline or INI
    metacharacter cannot inject structure into the generated ``config.ini``.
    """
    if value is None:
        return
    if not isinstance(value, dict):
        raise ConfigError("'config_ini' must be a mapping of sections")
    for section, keys in value.items():
        _reject_ini_token(section, f"config_ini section {section!r}")
        if not isinstance(keys, dict):
            raise ConfigError(f"'config_ini.{section}' must be a mapping")
        for key, scalar in keys.items():
            _reject_ini_token(key, f"config_ini.{section} key {key!r}")
            if not isinstance(scalar, (str, int, float, bool)):
                raise ConfigError(f"'config_ini.{section}.{key}' must be a scalar")
            if isinstance(scalar, str) and ("\n" in scalar or "\r" in scalar):
                raise ConfigError(
                    f"'config_ini.{section}.{key}' value must not contain newlines"
                )


def _reject_ini_token(token: object, what: str) -> None:
    """Reject a section/key name that is not a clean INI identifier."""
    if not isinstance(token, str):
        raise ConfigError(f"{what} must be a string")
    if any(ch in token for ch in "\n\r[]="):
        raise ConfigError(f"{what} must not contain newlines, '[', ']' or '='")


def _validate_performance(perf: object) -> None:
    """Validate the optional ``performance`` block."""
    if perf is None:
        return
    if not isinstance(perf, dict):
        raise ConfigError("'performance' must be a mapping")
    if "non_blocking_saving" in perf and not isinstance(
        perf["non_blocking_saving"], bool
    ):
        raise ConfigError("'performance.non_blocking_saving' must be a boolean")
    for key in ("nice", "cpu_weight", "io_weight"):
        value = perf.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise ConfigError(f"'performance.{key}' must be an integer")
    for key in ("cpu_affinity", "memory_high", "memory_max"):
        value = perf.get(key)
        if value is not None and not isinstance(value, str):
            raise ConfigError(f"'performance.{key}' must be a string")


def _validate_mapping(value: object, field: str) -> None:
    """Ensure an optional field is a mapping."""
    if value is not None and not isinstance(value, dict):
        raise ConfigError(f"'{field}' must be a mapping")


def _validate_str_list(value: object, field: str) -> None:
    """Ensure an optional field is a list of strings."""
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'{field}' must be a list of strings")


def _validate_port(port: object) -> None:
    """Ensure a port is an integer in the valid range."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ConfigError(f"'port' must be an integer 1-65535, got {port!r}")


def _validate_rcon(rcon: object) -> None:
    """Ensure an optional rcon block carries a port and password."""
    if rcon is None:
        return
    if not isinstance(rcon, dict):
        raise ConfigError("'rcon' must be a mapping with 'port' and 'password'")
    if "port" not in rcon or "password" not in rcon:
        raise ConfigError("'rcon' requires both 'port' and 'password'")
    _validate_port(rcon["port"])


#: ``game_version`` values that follow a channel symlink instead of naming a
#: concrete build. ``latest`` is an alias for the experimental channel.
_CHANNELS = {
    "": "current",
    "current": "current",
    "stable": "stable",
    "experimental": "experimental",
    "latest": "experimental",
}


def resolve_build(game_version: str) -> str:
    """Resolve a configured ``game_version`` to a concrete pool version.

    A channel name (``current``/``stable``/``experimental``/``latest``, or an
    empty value) follows the matching symlink; any other value must name an
    installed build. Channels are resolved to a concrete version at call time,
    so an assembled instance does not silently jump builds later.

    :raises ConfigError: if the channel or build is not present in the pool.
    """
    channel = _CHANNELS.get(game_version) if game_version is not None else "current"
    if channel:
        link = paths.channel_link(channel)
        if not link.is_symlink() and not link.exists():
            raise ConfigError(f"no {channel} build; {link} is missing")
        return _version_from_build_dir(Path(link.resolve()))
    build = paths.build_dir(game_version)
    if not build.is_dir():
        raise ConfigError(f"game version {game_version} is not installed")
    return game_version


def _version_from_build_dir(build: Path) -> str:
    """Extract the version string encoded in a ``factorio_<ver>`` directory."""
    stem = build.name
    prefix = "factorio_"
    if not stem.startswith(prefix):
        raise ConfigError(f"unexpected build directory name: {stem}")
    return stem[len(prefix):]


def load_credentials() -> dict:
    """Read Factorio account credentials for authenticated mod downloads.

    :returns: mapping with ``username`` and ``token`` keys.
    :raises ConfigError: if the secrets file is missing or incomplete.
    """
    path = paths.secrets_file()
    if not path.exists():
        raise ConfigError(f"no credentials file: {path}")
    with path.open() as handle:
        data = json.load(handle)
    if "username" not in data or "token" not in data:
        raise ConfigError("credentials must contain 'username' and 'token'")
    return data
