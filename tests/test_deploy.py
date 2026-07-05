import types

import pytest

from factorio_server_manager import deploy, remote


@pytest.fixture
def captured(monkeypatch):
    """Capture every subprocess argv the deployer runs; report success."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    return calls


def _rsync_calls(calls):
    return [c for c in calls if c and c[0] == "rsync"]


def test_deploy_source_uses_trailing_slash(tmp_path, captured):
    deploy.deploy_source("factorio", "server", tmp_path)
    rsyncs = _rsync_calls(captured)
    assert rsyncs, "expected an rsync invocation"
    source_arg = rsyncs[0][-2]
    dest_arg = rsyncs[0][-1]
    # Contents-copy semantics: source must end in a slash, not the dir name.
    assert source_arg == f"{tmp_path}/"
    assert dest_arg == "factorio@server:~/src/factorio-server-manager/"


def test_deploy_source_excludes_secrets(tmp_path, captured):
    deploy.deploy_source("factorio", "server", tmp_path)
    rsync = _rsync_calls(captured)[0]
    assert "secrets/credentials.json" in rsync
    assert "worlds/*.zip" in rsync


def test_deploy_instance_validates_name(tmp_path, captured):
    with pytest.raises(ValueError):
        deploy.deploy_instance("factorio", "server", tmp_path, "../evil")


def test_deploy_source_hints_on_venv_failure(tmp_path, monkeypatch):
    def fake_ssh(user, host, command):
        if "python3 -m venv" in command:
            raise remote.RemoteError("ssh command failed (1)")

    monkeypatch.setattr(remote, "ssh", fake_ssh)
    monkeypatch.setattr(remote, "rsync", lambda *a, **k: None)
    with pytest.raises(remote.RemoteError) as exc:
        deploy.deploy_source("factorio", "server", tmp_path)
    assert "python3-venv" in str(exc.value)  # actionable Debian/Ubuntu hint


def test_main_rejects_non_repo_source(tmp_path, captured):
    with pytest.raises(remote.RemoteError):
        deploy.main(["--host", "server", "--source", str(tmp_path)])


def test_main_runs_from_repo_source(tmp_path, captured):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert deploy.main(["--host", "server", "--source", str(tmp_path)]) == 0
    assert _rsync_calls(captured)  # source sync happened


def test_pull_saves_filters_and_direction(tmp_path, captured):
    deploy.pull_saves("factorio", "server", str(tmp_path / "out"))
    pulls = _rsync_calls(captured)
    assert pulls
    call = pulls[-1]
    # Portable excludes (no rsync-3.x include filters); secrets stay on the host.
    assert "--exclude=mods/" in call
    assert "--exclude=*.yaml" in call
    assert "--exclude=*.json" in call
    assert call[-2] == "factorio@server:~/instances/"  # remote source
    assert call[-1] == f"{tmp_path / 'out'}/"  # local dest
