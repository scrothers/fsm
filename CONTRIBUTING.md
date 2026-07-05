# Contributing

Thanks for your interest in improving factorio-server-manager.

## Development setup

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Running checks

```sh
.venv/bin/python -m pyflakes src/factorio_server_manager tests
.venv/bin/python -m pytest -q
```

Both must pass; CI runs them on Python 3.11, 3.12 and 3.13. The test suite is
hermetic — `FACTORIO_HOME` and `XDG_CONFIG_HOME` are redirected to a temp
directory and all network / systemd / subprocess calls are stubbed, so tests
never touch the real host, the mod portal, or your systemd units. Keep it that
way: mock external effects, and add coverage for any new behavior.

## Conventions

- **Stdlib first.** The only runtime dependency is `PyYAML`. Route all HTTP
  through `net.urlopen`; use `subprocess` for process control.
- **Layout is authoritative in one place.** All filesystem paths come from
  `paths.py`; never hardcode `/home/factorio` or reach outside it.
- **One error type per module** (`ConfigError`, `ModError`, ...), surfaced to a
  clean one-line `error:` at the CLI.
- **Validate input in `config.py`**, next to the other `_validate_*` helpers.
- **Document exported functions** with reST docstrings; keep private helpers
  `_prefixed`.
- No emoji, no em-dashes, no TODO/FIXME comments.

## Pull requests

- Keep changes focused; one concern per PR.
- Update the README / template reference and `CHANGELOG.md` when behavior changes.
- Ensure `pyflakes` and `pytest` are green before opening the PR.
