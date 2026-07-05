"""Local deployer: the ``fsm-deploy`` console script.

Run on a workstation. Pushes the package source to the server, (re)creates the
venv and installs the package into it, and installs/reloads the systemd user
unit. Optional flags push the credentials file, an instance's YAML, and the
default world. Pure Python driving ``ssh``/``rsync`` via :mod:`.remote`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import paths, remote

#: Repo root, derived from this file (works with an editable install).
REPO_ROOT = Path(__file__).resolve().parents[2]

REMOTE_SRC = "~/src/factorio-server-manager"
REMOTE_VENV = "~/venv"
REMOTE_UNIT_DIR = "~/.config/systemd/user"

SOURCE_EXCLUDES = [
    ".git",
    ".claude",
    "__pycache__",
    "*.pyc",
    "*.egg-info",
    ".pytest_cache",
    ".venv",
    "venv",
    "secrets/credentials.json",
    "worlds/*.zip",
]


def deploy_source(user: str, host: str, source: Path) -> None:
    """Sync source, build/refresh the venv, install the package."""
    remote.ssh(user, host, f"mkdir -p {REMOTE_SRC}")
    # Trailing slash: rsync copies the directory's *contents* into REMOTE_SRC.
    remote.rsync(
        user, host, f"{source}/", f"{REMOTE_SRC}/", excludes=SOURCE_EXCLUDES
    )
    try:
        remote.ssh(
            user,
            host,
            f"test -d {REMOTE_VENV} || python3 -m venv {REMOTE_VENV}",
        )
    except remote.RemoteError as exc:
        # Debian/Ubuntu split venv/pip out of the base python3 package.
        raise remote.RemoteError(
            f"{exc}\nhint: ensure python3 with venv and pip is installed on the "
            "host (Debian/Ubuntu: 'sudo apt install python3-venv python3-pip')"
        ) from exc
    remote.ssh(
        user,
        host,
        f"{REMOTE_VENV}/bin/pip install --quiet --upgrade pip "
        f"&& {REMOTE_VENV}/bin/pip install --quiet -e {REMOTE_SRC}",
    )


def deploy_unit(user: str, host: str) -> None:
    """Install the systemd user unit and reload the user manager."""
    remote.ssh(
        user,
        host,
        f"mkdir -p {REMOTE_UNIT_DIR} "
        f"&& {REMOTE_VENV}/bin/fsm systemd install",
    )


def deploy_secrets(user: str, host: str, source: Path) -> None:
    """Push the credentials file with restrictive permissions."""
    creds = source / "secrets" / "credentials.json"
    if not creds.exists():
        raise remote.RemoteError(f"missing {creds}")
    remote.ssh(user, host, "mkdir -p ~/secrets && chmod 700 ~/secrets")
    remote.rsync(user, host, creds, "~/secrets/credentials.json")
    remote.ssh(user, host, "chmod 600 ~/secrets/credentials.json")


def deploy_instance(user: str, host: str, source: Path, name: str) -> None:
    """Push a single instance's authored ``instance.yaml``."""
    paths.validate_name(name)  # guards the remote path and shell interpolation
    yaml_path = source / "instances" / name / "instance.yaml"
    if not yaml_path.exists():
        raise remote.RemoteError(f"missing {yaml_path}")
    remote.ssh(user, host, f"mkdir -p ~/instances/{name}")
    remote.rsync(
        user, host, yaml_path, f"~/instances/{name}/instance.yaml"
    )


def deploy_world(user: str, host: str, source: Path) -> None:
    """Push the default world used to seed new instances."""
    world = source / "worlds" / "world.zip"
    if not world.exists():
        raise remote.RemoteError(f"missing {world}")
    remote.ssh(user, host, "mkdir -p ~/worlds")
    remote.rsync(user, host, world, "~/worlds/world.zip")


def pull_saves(user: str, host: str, dest: str) -> None:
    """Pull every instance's saves and backups down to a local directory.

    Uses plain ``--exclude`` patterns (portable to the older rsync/openrsync that
    ships on macOS) rather than rsync-3.x include filters. Config and secret
    files (instance.yaml, the generated JSON/INI, mod symlinks) are excluded, so
    only save and backup zips are copied and nothing sensitive leaves the host.
    """
    Path(dest).mkdir(parents=True, exist_ok=True)
    excludes = [
        "--exclude=mods/",       # symlinks into the shared cache
        "--exclude=*.yaml",      # authored config (game/rcon passwords)
        "--exclude=*.json",      # generated config incl. rcon password
        "--exclude=*.ini",
    ]
    remote.rsync_pull(
        user, host, "~/instances/", f"{dest.rstrip('/')}/", options=excludes
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the deployer's argument parser."""
    parser = argparse.ArgumentParser(
        prog="fsm-deploy", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="factorio")
    parser.add_argument(
        "--source", type=Path, default=REPO_ROOT, help="local repo root"
    )
    parser.add_argument("--secrets", action="store_true", help="push credentials.json")
    parser.add_argument("--instance", help="push instances/<name>/instance.yaml")
    parser.add_argument("--world", action="store_true", help="push default world.zip")
    parser.add_argument(
        "--pull-saves",
        nargs="?",
        const="./saves-pull",
        metavar="DEST",
        help="pull instance saves and backups to a local directory",
    )
    parser.add_argument(
        "--no-code", action="store_true", help="skip source/venv/unit sync"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the requested deployment steps."""
    args = build_parser().parse_args(argv)
    user, host, source = args.user, args.host, args.source
    if not (source / "pyproject.toml").exists():
        raise remote.RemoteError(
            f"--source {source} is not a repo checkout (no pyproject.toml); "
            "run the deployer from the source tree or pass --source"
        )
    if not args.no_code:
        deploy_source(user, host, source)
        deploy_unit(user, host)
    if args.secrets:
        deploy_secrets(user, host, source)
    if args.instance:
        deploy_instance(user, host, source, args.instance)
    if args.world:
        deploy_world(user, host, source)
    if args.pull_saves:
        pull_saves(user, host, args.pull_saves)
    print("deploy complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
