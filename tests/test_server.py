import pytest
from helpers import make_build, make_credentials, make_default_world

from factorio_server_manager import instance, mods, server


def _assemble(fhome, monkeypatch):
    make_build(fhome, "1.1.110", current=True)
    make_credentials(fhome)
    make_default_world(fhome)
    cfg = fhome / "instances" / "main" / "instance.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "name: main\n"
        "port: 34210\n"
        "mods: []\n"
        "rcon: {port: 27015, password: secret}\n"
    )
    monkeypatch.setattr(mods, "fetch_mod_info", lambda name: {"releases": []})
    instance.assemble("main")


def test_build_argv_includes_core_flags(fhome, monkeypatch):
    _assemble(fhome, monkeypatch)
    argv = server.build_argv("main")
    assert argv[0].endswith("factorio")
    assert "--start-server" in argv
    assert "--port" in argv and "34210" in argv
    assert "--server-settings" in argv
    assert "--mod-directory" in argv


def test_build_argv_adds_rcon(fhome, monkeypatch):
    _assemble(fhome, monkeypatch)
    argv = server.build_argv("main")
    assert "--rcon-port" in argv and "27015" in argv
    assert "--rcon-password" in argv and "secret" in argv


def test_build_argv_unassembled_raises(fhome):
    with pytest.raises(server.RunError):
        server.build_argv("ghost")


def test_build_argv_access_and_extra_args(fhome, monkeypatch):
    make_build(fhome, "1.1.110", current=True)
    make_credentials(fhome)
    make_default_world(fhome)
    cfg = fhome / "instances" / "main" / "instance.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "name: main\nport: 34210\nmods: []\n"
        "whitelist:\n  - alice\n"
        "banlist:\n  - bad\n"
        'extra_args:\n  - "--bind"\n  - "0.0.0.0"\n'
    )
    monkeypatch.setattr(mods, "fetch_mod_info", lambda name: {"releases": []})
    instance.assemble("main")
    argv = server.build_argv("main")
    assert "--server-whitelist" in argv and "--use-server-whitelist" in argv
    assert "--server-banlist" in argv
    assert argv[-2:] == ["--bind", "0.0.0.0"]  # extra_args appended verbatim, last
