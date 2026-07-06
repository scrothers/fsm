# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-07-05

### Security

- Hardened headless-build tar extraction: the compatibility fallback (Python
  < 3.11.4, e.g. Debian 12) now validates each member's resolved path is within
  the destination and extracts it individually. The modern-Python `data` filter
  path is unchanged.

### Added

- GitHub Releases are now created automatically on version tags, with notes from
  this changelog and the built sdist/wheel attached.
- Security policy (`SECURITY.md`), Dependabot version updates, and CodeQL code
  scanning.

## [1.0.0] - 2026-07-05

Initial public release.

### Game builds and mods

- Shared game-build pool with `stable`/`experimental`/`current` channel symlinks;
  `fsm binary install` / `update` / `list` / `current`.
- Keep-forever mod cache with dependency resolution, SHA-1 verification, and
  per-version game-version metadata; `fsm mods update` / `download` / `refresh` /
  `info` / `list`, including `--game-version all`.

### Instances

- Declarative instances assembled from `instance.yaml`: isolation `config.ini`,
  `server-settings.json`, admin/whitelist/ban lists, RCON, `extra_args`,
  performance (non-blocking saving + systemd resource drop-ins) and a raw
  `config.ini` passthrough.
- `fsm instance new` (auto free port), `assemble`, `create-map`, `remove`, `list`.
- Pinned mods incompatible with the instance's game build emit a warning.

### Operations

- systemd `@` user template unit; `fsm run` (`os.execv`), control wrappers,
  `fsm rcon` (multi-packet aware), map generation, and rotated save backups.
- `fsm systemd install` / `install-timers` (daily mod-refresh, weekly channel
  update).
- `fsm doctor [--online]` preflight health checks (lingering, systemd user
  manager, credentials, current build, free disk, cgroup controller delegation,
  optional connectivity).
- `fsm --version`.

### Packaging and tooling

- Installable as `factorio-server-manager` (import `factorio_server_manager`);
  console scripts `fsm` and `fsm-deploy`. Stdlib only except PyYAML; ships a
  `py.typed` marker and PEP 639 SPDX license metadata.
- Local deployer over ssh/rsync (`fsm-deploy`) with `--secrets` / `--instance` /
  `--world` / `--pull-saves`; hints to install `python3-venv`/`python3-pip` when
  host venv creation fails.
- Distro-agnostic (any systemd Linux, Python 3.11+). CI runs the suite on real
  containers for the current and previous release of Debian, Ubuntu LTS, and
  Fedora; tag-triggered PyPI publishing via Trusted Publishing.
