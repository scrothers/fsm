"""The ``fsm run`` entry point used as systemd ``ExecStart``.

Reads an instance's generated runtime facts, builds the Factorio argument
vector, and replaces the process image with the game binary via ``os.execv`` so
that systemd supervises the real server process (and SIGINT reaches it for a
clean save on stop).
"""

from __future__ import annotations

import json
import os

from . import config, paths


class RunError(Exception):
    """Raised when an instance cannot be launched."""


def build_argv(name: str) -> list[str]:
    """Assemble the Factorio command line for an instance.

    :raises RunError: if the instance has not been assembled or its build or
        save is missing.
    """
    runtime_file = paths.instance_runtime(name)
    if not runtime_file.exists():
        raise RunError(f"instance not assembled: run 'fsm instance assemble {name}'")
    runtime = json.loads(runtime_file.read_text())

    version = config.resolve_build(runtime["game_version"])
    binary = paths.binary_path(paths.build_dir(version))
    if not binary.exists():
        raise RunError(f"binary missing for version {version}: {binary}")

    inst = paths.instance_dir(name)
    save = paths.instance_saves(name) / runtime["save"]
    if not save.exists():
        raise RunError(f"save missing: {save}")

    argv = [
        str(binary),
        "--config", str(inst / "config.ini"),
        "--start-server", str(save),
        "--server-settings", str(inst / "server-settings.json"),
        "--server-adminlist", str(inst / "server-adminlist.json"),
        "--mod-directory", str(paths.instance_mods(name)),
        "--port", str(runtime["port"]),
    ]
    rcon = runtime.get("rcon")
    if rcon:
        argv += [
            "--rcon-port", str(rcon["port"]),
            "--rcon-password", str(rcon["password"]),
        ]
    if runtime.get("whitelist"):
        argv += [
            "--server-whitelist", str(inst / "server-whitelist.json"),
            "--use-server-whitelist",
        ]
    if runtime.get("banlist"):
        argv += ["--server-banlist", str(inst / "server-banlist.json")]
    argv += list(runtime.get("extra_args", []))
    return argv


def run(name: str) -> None:
    """Launch an instance by replacing this process with the game binary."""
    argv = build_argv(name)
    os.execv(argv[0], argv)
