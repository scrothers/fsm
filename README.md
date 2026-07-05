# Factorio Server Manager

[![PyPI](https://img.shields.io/pypi/v/factorio-server-manager.svg)](https://pypi.org/project/factorio-server-manager/)
[![Python](https://img.shields.io/pypi/pyversions/factorio-server-manager.svg)](https://pypi.org/project/factorio-server-manager/)
[![CI](https://github.com/scrothers/fsm/actions/workflows/ci.yml/badge.svg)](https://github.com/scrothers/fsm/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE.md)

Manage multiple isolated Factorio headless servers on one host under systemd
user template units. One shared binary pool, many instances, each assembled from
a single YAML file. Every game build and every mod version ever downloaded is
kept forever; instances select which versions they use.

```sh
pip install factorio-server-manager     # provides the `fsm` and `fsm-deploy` commands
# or straight from source:
pip install git+https://github.com/scrothers/fsm
```

- **Package:** `factorio_server_manager` (`pip install factorio-server-manager`);
  commands `fsm` (server-side) and `fsm-deploy` (workstation). Stdlib only except
  `PyYAML` (one runtime dependency).
- **Runs on the server** (any Linux host with systemd) inside a venv at `~/venv`.
- **Deployed** from a workstation with `fsm-deploy` over ssh/rsync (the
  `factorio` user is key-authenticated).

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Server layout](#server-layout)
- [One-time setup](#one-time-setup)
- [Deployment](#deployment)
- [Quickstart](#quickstart)
- [Instance configuration reference](#instance-configuration-reference)
- [Command reference](#command-reference)
- [Game version pool and channels](#game-version-pool-and-channels)
- [Mod pool](#mod-pool)
- [Performance](#performance)
- [Operating a live server](#operating-a-live-server)
- [Systemd unit](#systemd-unit)
- [Security notes](#security-notes)
- [Development](#development)

---

## How it works

- **One binary, many instances.** All instances run off a shared, versioned
  headless build. Each instance lives in its own directory and is isolated via a
  generated `config.ini` whose `[path]` sets `read-data` to the build's shared
  `data/` and `write-data` to the instance directory. Saves, mods, config and
  `player-data.json` are therefore per-instance while the binary and game data
  are shared.
- **Keep-forever pools.** Game builds (`server/factorio_<ver>/`) and mod versions
  (`mods-cache/<mod>/<mod>_<ver>.zip`) are never deleted. Instances point at the
  versions they use (build symlink; mod symlinks into the cache).
- **Declarative instances.** `instances/<name>/instance.yaml` is the source of
  truth. `fsm instance assemble <name>` materializes everything derived from it
  (config, server settings, access lists, mod links, runtime facts, systemd
  drop-in) idempotently, and never clobbers an existing save.
- **systemd @ template unit.** `systemctl --user start|enable factorio@<name>`.
  `ExecStart` is `fsm run <name>`, which `os.execv`s the game binary so systemd
  supervises the real process.

---

## Requirements

- **Host:** any Linux distribution with systemd and Python 3.11+. Tested targets:
  Debian 12/13, Ubuntu 24.04 LTS, and Fedora. The server needs Python with the
  `venv` and `pip` modules — on Debian/Ubuntu these are separate packages:
  ```sh
  sudo apt install python3 python3-venv python3-pip
  ```
  (On Fedora/RHEL the base `python3` already includes them.)
- **Workstation:** Python 3.11+, `ssh` and `rsync`, key-based SSH access to
  `factorio@server`.
- **Factorio account** with a service token (mods and public server listing).

The tool is distro-agnostic: it only uses systemd (`systemctl --user`, drop-ins,
user lingering), `ssh`/`rsync`, and a Python venv. It does **not** manage the
host firewall — open each instance's UDP port (default `34197`) in whatever the
host uses (`ufw`, `nftables`, `firewalld`, cloud security group, or none). No
SELinux/AppArmor changes are needed: the headless binary runs unconfined from the
`factorio` user's home under the default policies.

> Throughout this document `server` is the example host and `factorio` the
> example user; substitute your own.

---

## Server layout

Everything lives under the `factorio` user's home (`/home/factorio`):

```
venv/                                  python venv with factorio_server_manager + PyYAML
src/factorio-server-manager/                  synced source (pip install -e target)

server/                                GAME VERSION POOL (every build kept forever)
  current -> factorio_<ver>/           default build for game_version: current
  stable -> factorio_<ver>/            newest installed stable build
  experimental -> factorio_<ver>/      newest installed experimental build
  factorio_<ver>/factorio/bin/x64/factorio

mods-cache/                            MOD POOL (every version kept forever)
  <mod>/<mod>_<ver>.zip
  <mod>/metadata.json                  records each version's Factorio major.minor

instances/<name>/
  instance.yaml                        authored config (source of truth)
  config.ini                           generated: read-data shared, write-data local
  server-settings.json                 generated (+ credentials injected)  [chmod 600]
  server-adminlist.json                generated from server_settings.admins
  server-whitelist.json                generated when whitelist set
  server-banlist.json                  generated when banlist set
  map-gen-settings.json                generated when map_gen_settings set
  map-settings.json                    generated when map_settings set
  instance.json                        generated runtime facts for fsm run  [chmod 600]
  mods/                                mod-list.json + symlinks into mods-cache
  saves/<save>.zip
  backups/<save>_<timestamp>.zip       rotated save snapshots

secrets/credentials.json               account username + service token  [chmod 600]
worlds/world.zip                       default world seeded into new instances

~/.config/systemd/user/
  factorio@.service                    the template unit
  factorio@<name>.service.d/performance.conf   per-instance resource drop-in
```

---

## One-time setup

1. **Enable lingering** (as root on the host) so user units survive logout and
   start on boot:
   ```sh
   loginctl enable-linger factorio
   ```
2. **Credentials.** Copy `secrets/credentials.json.example` to
   `secrets/credentials.json` and fill in your factorio.com username and service
   token (find the token at <https://factorio.com/profile>).
3. **Install the deployer on your workstation.** `fsm-deploy` rsyncs a repo
   checkout to the server, so clone the repo and install it (editable, so
   `--source` auto-detects the checkout):
   ```sh
   git clone https://github.com/scrothers/fsm && cd fsm
   python -m venv .venv && .venv/bin/pip install -e .
   ```
   (If you `pip install factorio-server-manager` without a checkout, pass
   `fsm-deploy --source /path/to/clone`.)

---

## Deployment

The deployer runs on your workstation and drives `ssh`/`rsync`:

```sh
fsm-deploy --host server [options]
```

| Option | Effect |
| --- | --- |
| `--host HOST` | Target host (required). |
| `--user USER` | SSH user (default `factorio`). |
| `--source DIR` | Local repo root (default: auto-detected). |
| *(default)* | rsync source, create/refresh `~/venv`, install the systemd unit, `daemon-reload`. |
| `--secrets` | Push `secrets/credentials.json` (mode 600). |
| `--instance NAME` | Push `instances/NAME/instance.yaml`. |
| `--world` | Push `worlds/world.zip` (the default seed world). |
| `--pull-saves [DEST]` | Pull every instance's `saves/` and `backups/` down to `DEST` (default `./saves-pull`). |
| `--no-code` | Skip the source/venv/unit sync (do only the flagged actions). |

The default (unflagged) run always syncs code and the unit; combine with
`--no-code` for a pure operation, e.g. a backup pull:

```sh
fsm-deploy --host server --no-code --pull-saves ./backups
```

---

## Quickstart

```sh
# 1. push source, build the venv, install the systemd unit
fsm-deploy --host server

# 2. push credentials and the default world
fsm-deploy --host server --secrets --world

# 3. install a game build and make it the default
ssh factorio@server '~/venv/bin/fsm binary install --make-current'

# 4. author instances/main/instance.yaml locally, push it, assemble it
fsm-deploy --host server --instance main
ssh factorio@server '~/venv/bin/fsm instance assemble main'

# 5. enable + start, then watch the log
ssh factorio@server '~/venv/bin/fsm enable main && ~/venv/bin/fsm start main'
ssh factorio@server '~/venv/bin/fsm logs main -f'
```

Connect a client to `server:<port>`. To generate a fresh world instead of using
the seeded `world.zip`, run `fsm instance create-map main` after step 4.

---

## Instance configuration reference

An instance is defined entirely by `instances/<name>/instance.yaml`. The
directory name is authoritative; a `name:` in the file is ignored. A starter
lives at `src/factorio_server_manager/templates/instance.yaml.example`.

> `instances/*/instance.yaml` is git-ignored because it carries the game and
> RCON passwords. Only `instance.yaml.example` is tracked. Keep real configs
> local or in a private store.

### Full example

```yaml
name: main                      # ignored; the directory name wins
game_version: current           # channel (current/stable/experimental/latest) or 2.1.9
port: 34197                     # UDP port (unique per instance)
save: world.zip                 # save file inside saves/

server_settings:                # merged over the defaults below
  name: "Server Main"
  description: "Factorio multiplayer server"
  tags: []
  visibility: { public: true, lan: true }
  game_password: ""
  max_players: 0
  admins:                       # -> server-adminlist.json (not part of settings)
    - your-factorio-username
  autosave_interval: 10
  autosave_slots: 5
  autosave_only_on_server: true
  afk_autokick_interval: 0
  max_heartbeats_per_second: 60
  max_upload_in_kilobytes_per_second: 0
  max_upload_slots: 5
  minimum_latency_in_ticks: 0
  allow_commands: admins-only
  auto_pause: true
  only_admins_can_pause_the_game: true
  require_user_verification: true

mods:
  - name: even-distribution     # no version -> track latest for the game build
  - name: FNEI
    version: 0.4.1              # pinned -> frozen; never auto-updated

rcon:
  port: 27015
  password: "change-me"

whitelist:                      # non-empty -> only these users may connect
  - alice
  - bob
banlist:
  - griefer123

extra_args:                     # any other factorio flags, appended verbatim
  - "--bind"
  - "0.0.0.0"

performance:
  non_blocking_saving: true     # config.ini [other]; default on
  cpu_affinity: "2-7"           # systemd CPUAffinity
  nice: 5                       # systemd Nice
  cpu_weight: 200               # systemd CPUWeight
  io_weight: 200                # systemd IOWeight
  memory_high: "6G"             # systemd MemoryHigh
  memory_max: "8G"              # systemd MemoryMax

seed: 123456789                 # map generation seed (create-map)
map_gen_settings:               # -> map-gen-settings.json (create-map)
  width: 0                      # 0 = infinite
map_settings:                   # -> map-settings.json (create-map)
  pollution: { enabled: true }
```

### Top-level keys

| Key | Type | Default | Purpose |
| --- | --- | --- | --- |
| `game_version` | string | `current` | Build to run: a channel (`current`/`stable`/`experimental`/`latest`) or a concrete version like `2.1.9`. Resolved to a concrete build **at assemble time**. |
| `port` | int | `34197` | UDP listen port. Must be unique per instance (assemble warns on conflicts). |
| `save` | string | `world.zip` | Save file loaded from `saves/`. |
| `mods` | list | `[]` | Mods to enable (see below). |
| `server_settings` | mapping | see defaults | Overlaid onto the multiplayer defaults; written to `server-settings.json`. |
| `rcon` | mapping | — | `{ port, password }`; enables remote console. |
| `whitelist` | list of str | — | Allowed usernames. Non-empty enforces a whitelist. |
| `banlist` | list of str | — | Banned usernames. |
| `extra_args` | list of str | — | Extra Factorio flags, appended verbatim (each token a list item). |
| `performance` | mapping | — | Non-blocking saving and systemd resource controls (see [Performance](#performance)). |
| `config_ini` | mapping | — | Extra `config.ini` settings as `section -> {key: value}`, merged over the generated `[path]`/`[other]`. |
| `seed` | int | — | Map generation seed for `create-map`. |
| `map_gen_settings` | mapping | — | Map generation settings for `create-map`. |
| `map_settings` | mapping | — | Map settings for `create-map`. |

### `mods` entries

Each entry is a mapping with a `name` and an optional `version`:

```yaml
mods:
  - name: even-distribution     # tracks the latest release for the game build
  - name: FNEI
    version: 0.4.1              # pinned exactly; never touched by mods update
```

Required dependencies of listed mods are resolved and installed automatically.
Built-ins (`base`, `space-age`, `elevated-rails`, `quality`) are recognized and
never fetched from the portal.

### `server_settings` defaults

The block is deep-merged over these defaults; `username`/`token` are injected
from `secrets/credentials.json` (needed for a public listing), and `admins` is
split out into `server-adminlist.json`.

| Key | Default |
| --- | --- |
| `name` | `Factorio` |
| `description` | `""` |
| `tags` | `[]` |
| `max_players` | `0` (unlimited) |
| `visibility` | `{ public: false, lan: true }` |
| `game_password` | `""` |
| `require_user_verification` | `true` |
| `max_upload_in_kilobytes_per_second` | `0` (unlimited) |
| `max_upload_slots` | `5` |
| `allow_commands` | `admins-only` |
| `autosave_interval` | `10` (minutes) |
| `autosave_slots` | `5` |
| `afk_autokick_interval` | `0` (disabled) |
| `auto_pause` | `true` |
| `only_admins_can_pause_the_game` | `true` |
| `autosave_only_on_server` | `true` |

### Access control and extra flags

- `whitelist:` — when non-empty, assembly writes `server-whitelist.json` and
  `fsm run` passes `--server-whitelist <file> --use-server-whitelist`.
- `banlist:` — writes `server-banlist.json`, passed via `--server-banlist`.
- `admins:` (under `server_settings`) — writes `server-adminlist.json`, passed
  via `--server-adminlist`.
- `extra_args:` — appended verbatim to the command line as separate argv tokens
  (no shell), the escape hatch for any flag without first-class support.

After editing any of these, re-run `fsm instance assemble <name>` and restart the
instance.

---

## Command reference

`fsm` runs on the server (`~/venv/bin/fsm`). Every command exits non-zero with a
one-line `error:` message on failure.

### Game builds (`binary`)

| Command | Purpose |
| --- | --- |
| `binary install [--version V] [--make-current]` | Download and extract a build into the pool. `--version` is `stable` (default), `experimental` (alias `latest`), or a concrete version like `2.1.9`. `--make-current` points `current` at it. |
| `binary update` | Refresh every opted-in channel (a channel whose symlink exists) to its latest published build; download only when new. |
| `binary current <version>` | Point the `current` symlink at an installed build. |
| `binary list` | List installed builds, tagged with the channels pointing at each. |

### Instances (`instance`)

| Command | Purpose |
| --- | --- |
| `instance new <name> [--port N]` | Scaffold a starter `instance.yaml` (auto-assigns the next free port). |
| `instance assemble <name>` | Materialize the instance directory from its YAML (config, settings, access lists, mods, runtime facts, performance drop-in). Idempotent; never clobbers an existing save. |
| `instance create-map <name> [--force] [--seed N]` | Generate `saves/<save>` from the instance's map settings. `--force` overwrites; `--seed` overrides the YAML seed. |
| `instance remove <name> --force` | Stop, disable and delete the instance **and its saves** (`--force` required). |
| `instance list` | List configured instances. |

### Mods (`mods`)

| Command | Purpose |
| --- | --- |
| `mods update --instance <name>` | Refresh the instance's unpinned mods to the latest compatible release (also the systemd pre-run step). |
| `mods download <name> [--version V] [--game-version GV]` | Cache a mod and its dependencies without any instance. |
| `mods refresh [--game-version GV]` | Cache the latest compatible version of every known mod (cache + all instance-configured mods). |
| `mods info <name> [--game-version GV]` | Show a mod's latest release, the pick per game version, dependencies, and cache state. |
| `mods list` | List cached mods and versions, tagged with their game version. |

`--game-version` accepts a concrete version, a `major.minor`, or `all` (both the
current stable and experimental channels); it defaults to the current build.

### Control and live ops

| Command | Purpose |
| --- | --- |
| `start` / `stop` / `enable` / `disable` / `status <name>` | `systemctl --user` wrappers for the instance's unit. |
| `logs <name> [-f]` | Show the instance's journal; `-f` follows. |
| `run <name>` | Launch the instance (used as systemd `ExecStart`; `os.execv`s the binary). |
| `rcon <name> <command...>` | Run a console command against the live server over RCON. |
| `backup <name> [--keep N]` | Snapshot the newest save into a rotated `backups/` (default keep 10). |

### Reporting and setup

| Command | Purpose |
| --- | --- |
| `show versions [--available]` | Installed builds (with channels), cached mod versions, per-instance mod links. `--available` also queries the portals for the newest published versions. |
| `doctor [--online]` | Run preflight health checks (see below). |
| `systemd install` | Install the user template unit and `daemon-reload`. |
| `systemd install-timers` | Install and enable the scheduled-maintenance timers. |
| `--version` | Print the `fsm` version. |

### Health checks (`doctor`)

`fsm doctor` reports readiness as a status list (`ok` / `WARN` / `FAIL`):
lingering enabled, systemd user manager reachable, credentials present, a current
build installed, free disk on the pool filesystem, and which cgroup controllers
(`cpu`/`io`/`memory`) are delegated — so you know before setting
`performance.memory_max` whether the limit will actually take effect. `--online`
also checks factorio.com connectivity. Exits non-zero only if a check fails.

### Scheduled maintenance (`systemd install-timers`)

Installs and enables two `--user` timers that keep the pools fresh unattended:
`fsm-mods-refresh.timer` (daily → `fsm mods refresh --game-version all`) and
`fsm-binary-update.timer` (weekly → `fsm binary update`). Both keep-forever, so
they only ever add builds and mod versions.

---

## Game version pool and channels

Every build is kept in `server/` forever. Three symlinks track defaults:

- `current` — the default build for `game_version: current`.
- `stable` / `experimental` — the newest build installed for each channel.

Installing with a channel token maintains that channel's symlink; installing a
concrete version does not touch any channel symlink. `--make-current` (or the
first-ever install) also sets `current`.

`fsm binary update` fetches the latest published build for every channel whose
symlink exists (your opt-in signal), downloads it if new, and repoints the
symlink. Channels you never installed are left alone.

`game_version:` is resolved to a concrete build **at assemble time** and recorded
in `instance.json`, so a save never silently jumps versions. A moved channel does
not affect a running instance until you re-run `fsm instance assemble <name>`; a
plain restart keeps the frozen version.

You can run stable and experimental instances side by side off one deployment,
each pinning a different `game_version`.

---

## Mod pool

`mods-cache/<mod>/<mod>_<ver>.zip` holds every mod version ever downloaded and is
never pruned. An instance's `mods/` directory holds symlinks into the cache for
exactly the versions it uses; downloads are SHA-1 verified against the portal.

Resolution: an unpinned mod tracks the newest release whose `factorio_version`
matches the game build's `major.minor`; a pinned mod resolves to that exact
version. Required dependencies are pulled in automatically.

Direct cache management (no instance required):

- `mods download <name>` — fetch a mod and its dependencies (pin with
  `--version`).
- `mods refresh` — cache the latest compatible version of every known mod:
  everything already cached **plus** every mod configured in any instance
  (including ones not yet downloaded). Mods with no release for the target game
  version are skipped, not errored. `mods refresh --game-version all` is the
  one-shot "download all mod updates for both the current stable and experimental
  game versions" and is the natural command to run on a schedule.
- `mods info <name>` — inspect releases and cache state.

`--game-version all` targets both game channels, so a mod is cached once per
channel (e.g. the `2.0` and `2.1` builds, often different mod versions). Each
cached zip records the Factorio `major.minor` it was fetched for in a
`mods-cache/<mod>/metadata.json` sidecar, so `mods list` and `mods info` tag every
version with its game version (e.g. `2.1.0 (2.1), 1.0.10 (2.0)`).

The systemd pre-run (`ExecStartPre=fsm mods update`) refreshes an instance's
unpinned mods before each start; it is non-fatal, so a mod-portal hiccup never
blocks the server.

---

## Performance

Tuning fans out across the surfaces the manager generates.

**Background / threaded / non-blocking saves — `non_blocking_saving` (default
on).** These are the same Factorio feature: a forked child writes the save while
the parent keeps simulating, so autosaves never freeze the game. It is the
biggest smoothness win on a busy server. The one key
`performance.non_blocking_saving` is written to **both** `config.ini`
(`[other] non-blocking-saving`) and `server-settings.json` (`non_blocking_saving`)
so it is honored regardless of which the engine reads. Disable with
`performance.non_blocking_saving: false`.

**Multi-threading.** Factorio auto-multithreads entity updates across cores and
exposes **no thread-count setting**; `cpu_affinity` (below) is how you steer which
cores an instance uses. Any other engine setting can be set through the
`config_ini` passthrough, e.g.:

```yaml
config_ini:
  other:
    enable-new-mod-download: false
```

**systemd resource drop-in.** The remaining `performance:` keys render to
`~/.config/systemd/user/factorio@<name>.service.d/performance.conf` and
`daemon-reload` on assemble. Removing the keys clears the drop-in.

| YAML key | systemd directive | Notes |
| --- | --- | --- |
| `cpu_affinity` | `CPUAffinity` | Pin cores (e.g. `"2-7"`). Unprivileged; keeps instances off each other's cores. |
| `nice` | `Nice` | Positive is unprivileged; negative needs privilege. |
| `cpu_weight` | `CPUWeight` | cgroup weight; needs the cpu controller delegated to the user manager. |
| `io_weight` | `IOWeight` | cgroup weight; needs the io controller delegated. |
| `memory_high` | `MemoryHigh` | Soft limit (e.g. `"6G"`). |
| `memory_max` | `MemoryMax` | Hard limit (e.g. `"8G"`). |

> `CPUAffinity` and positive `Nice` work out of the box. The cgroup directives
> (`CPUWeight`/`IOWeight`/`MemoryHigh`/`MemoryMax`) and negative `Nice` require
> controller delegation or privilege for the `--user` manager; without it systemd
> ignores or rejects them. Run `fsm doctor` to see which controllers are
> delegated before relying on a limit.

**`server_settings:` — network and autosave knobs.** `autosave_interval`,
`autosave_slots`, `autosave_only_on_server` (default true),
`max_heartbeats_per_second`, `max_upload_in_kilobytes_per_second`,
`max_upload_slots`, `minimum_latency_in_ticks`, `afk_autokick_interval`.

**`extra_args:`** covers any other flag.

Re-run `fsm instance assemble <name>` and restart after changing any of these.

---

## Operating a live server

- **RCON** — `fsm rcon <name> "/players"` runs any console command against the
  running server (players, `/save`, `/promote`, `/ban`, broadcasts). It reads the
  port and password from `instance.json` and connects over loopback.
- **Map creation** — `fsm instance create-map <name>` generates `saves/<save>`
  from the instance's `map_gen_settings` / `map_settings` / `seed` (assemble
  first). `--force` overwrites an existing save; `--seed` overrides the YAML seed.
  Mods are loaded during generation if present. Use this instead of supplying a
  prebuilt `world.zip`.
- **Backups** — `fsm backup <name>` copies the newest save (including autosaves)
  into a rotated `instances/<name>/backups/`, keeping `--keep` (default 10). Pull
  them to your workstation with
  `fsm-deploy --host server --no-code --pull-saves DEST`.
  Both are good on a timer.

---

## Systemd unit

`factorio@.service` is a user template unit:

- `ExecStartPre=-fsm mods update --instance %i` — refresh unpinned mods
  (non-fatal; a portal hiccup does not block start).
- `ExecStart=fsm run %i` — `os.execv`s the game binary, so systemd supervises the
  real process and a stop delivers a clean SIGINT save.
- `Type=exec`, `Restart=on-failure` with a start-rate limit, `KillSignal=SIGINT`
  and a stop timeout for clean saves.

Per-instance resource controls come from the generated `performance.conf`
drop-in. `loginctl enable-linger factorio` (one-time, root) makes user units
survive logout and start on boot.

---

## Security notes

- **Secrets at rest.** `credentials.json`, `server-settings.json` (account token,
  game password) and `instance.json` (RCON password) are written mode 600. Real
  instance YAML is git-ignored.
- **RCON password.** Factorio has no password-file flag, so `fsm run` passes
  `--rcon-password` on the command line, where it is visible in `ps` and
  `systemctl --user status`. Acceptable on a single-operator host; keep RCON bound
  to localhost and do not expose its port.
- **Downloads** are SHA-1 verified (mods) and fetched over HTTPS from first-party
  hosts with an explicit User-Agent.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

---

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pyflakes src/factorio_server_manager tests
.venv/bin/python -m pytest -q
```

The suite is hermetic: `FACTORIO_HOME` (and `XDG_CONFIG_HOME`) are redirected to a
temp directory and all network/systemd/subprocess calls are stubbed, so no test
touches the real host, portal, or your systemd units. CI runs the full suite on
real containers for the current and previous release of each distro — **Debian
13/12**, **Ubuntu 26.04/24.04 LTS**, and **Fedora 44/43** — each doing a
from-scratch system-Python venv install, so cross-distro packaging and behavior
are exercised for real. See [CONTRIBUTING.md](CONTRIBUTING.md) for
conventions and
[CHANGELOG.md](CHANGELOG.md) for release notes. Licensed under
[MIT](LICENSE.md).

### Releasing

Publishing to PyPI is automated via Trusted Publishing (OIDC — no stored token):
bump `version` in `pyproject.toml`, update `CHANGELOG.md`, then push a matching
tag and let CI build and publish:

```sh
git tag v0.1.0 && git push origin v0.1.0
```

The `.github/workflows/release.yml` job builds the sdist + wheel and uploads them.
Configure the publisher once at the project's PyPI *Publishing* settings (owner
`scrothers`, repo `fsm`, workflow `release.yml`, environment `pypi`).
