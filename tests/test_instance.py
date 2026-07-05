import json

import pytest
from helpers import make_build, make_credentials, make_default_world

from factorio_server_manager import instance, mods, paths


def _release(mod, version, fv="1.1"):
    return {
        "version": version,
        "download_url": f"/download/{mod}/x",
        "info_json": {"factorio_version": fv},
    }


def _setup(fhome, monkeypatch, mods_yaml):
    make_build(fhome, "1.1.110", current=True)
    make_credentials(fhome)
    make_default_world(fhome)
    cfg = fhome / "instances" / "main" / "instance.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "name: main\n"
        "game_version: current\n"
        "port: 34200\n"
        "server_settings:\n"
        "  name: Test\n"
        "  visibility: {public: true, lan: true}\n"
        "  admins: [alice]\n"
        f"{mods_yaml}"
    )

    def fake_info(name):
        return {"name": name, "releases": [_release(name, "1.2.3")]}

    def fake_cache(mod, rel, creds):
        path = mods.cache_path(mod, rel["version"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"zip")
        return path

    monkeypatch.setattr(mods, "fetch_mod_info", fake_info)
    monkeypatch.setattr(mods, "ensure_cached", fake_cache)


def test_assemble_generates_all_files(fhome, monkeypatch):
    _setup(fhome, monkeypatch, "mods:\n  - name: even-distribution\n")
    summary = instance.assemble("main")
    inst = paths.instance_dir("main")

    config_ini = (inst / "config.ini").read_text()
    assert str(paths.data_dir(paths.build_dir("1.1.110"))) in config_ini
    assert f"write-data={inst}" in config_ini

    settings = json.loads((inst / "server-settings.json").read_text())
    assert settings["name"] == "Test"
    assert settings["username"] == "tester"
    assert settings["visibility"]["public"] is True

    admins = json.loads((inst / "server-adminlist.json").read_text())
    assert admins == ["alice"]

    runtime = json.loads(paths.instance_runtime("main").read_text())
    assert runtime["port"] == 34200
    assert runtime["game_version"] == "1.1.110"

    mod_list = json.loads((paths.instance_mods("main") / "mod-list.json").read_text())
    assert {"name": "base", "enabled": True} in mod_list["mods"]

    link = paths.instance_mods("main") / "even-distribution_1.2.3.zip"
    assert link.is_symlink()
    assert summary["version"] == "1.1.110"


def test_assemble_seeds_world_once(fhome, monkeypatch):
    _setup(fhome, monkeypatch, "mods: []\n")
    instance.assemble("main")
    save = paths.instance_saves("main") / "world.zip"
    assert save.exists()

    save.write_bytes(b"progress")  # simulate gameplay
    instance.assemble("main")  # re-assemble must not clobber
    assert save.read_bytes() == b"progress"


def test_list_instances(fhome, monkeypatch):
    _setup(fhome, monkeypatch, "mods: []\n")
    assert instance.list_instances() == ["main"]


def test_assemble_writes_access_lists(fhome, monkeypatch):
    _setup(
        fhome,
        monkeypatch,
        "mods: []\n"
        "whitelist:\n  - alice\n"
        "banlist:\n  - bad\n"
        'extra_args:\n  - "--bind"\n  - "0.0.0.0"\n',
    )
    instance.assemble("main")
    inst = paths.instance_dir("main")
    assert json.loads((inst / "server-whitelist.json").read_text()) == ["alice"]
    assert json.loads((inst / "server-banlist.json").read_text()) == ["bad"]
    runtime = json.loads(paths.instance_runtime("main").read_text())
    assert runtime["whitelist"] is True
    assert runtime["banlist"] is True
    assert runtime["extra_args"] == ["--bind", "0.0.0.0"]


def test_assemble_without_access_lists(fhome, monkeypatch):
    _setup(fhome, monkeypatch, "mods: []\n")
    instance.assemble("main")
    inst = paths.instance_dir("main")
    assert not (inst / "server-whitelist.json").exists()
    runtime = json.loads(paths.instance_runtime("main").read_text())
    assert runtime["whitelist"] is False
    assert runtime["extra_args"] == []


def test_assemble_non_blocking_saving_default(fhome, monkeypatch):
    _setup(fhome, monkeypatch, "mods: []\n")
    instance.assemble("main")
    ini = (paths.instance_dir("main") / "config.ini").read_text()
    assert "non-blocking-saving=true" in ini


def test_assemble_non_blocking_saving_off(fhome, monkeypatch):
    _setup(
        fhome, monkeypatch, "mods: []\nperformance:\n  non_blocking_saving: false\n"
    )
    instance.assemble("main")
    ini = (paths.instance_dir("main") / "config.ini").read_text()
    assert "non-blocking-saving" not in ini
    settings = json.loads(
        (paths.instance_dir("main") / "server-settings.json").read_text()
    )
    assert settings["non_blocking_saving"] is False


def test_assemble_non_blocking_saving_in_server_settings(fhome, monkeypatch):
    _setup(fhome, monkeypatch, "mods: []\n")
    instance.assemble("main")
    settings = json.loads(
        (paths.instance_dir("main") / "server-settings.json").read_text()
    )
    assert settings["non_blocking_saving"] is True  # written to both surfaces


def test_assemble_config_ini_passthrough(fhome, monkeypatch):
    _setup(
        fhome,
        monkeypatch,
        "mods: []\n"
        "config_ini:\n"
        "  other:\n"
        "    enable-new-mod-download: false\n"
        "  general:\n"
        "    locale: en\n",
    )
    instance.assemble("main")
    ini = (paths.instance_dir("main") / "config.ini").read_text()
    assert "enable-new-mod-download=false" in ini  # bool rendered lowercase
    assert "[general]" in ini and "locale=en" in ini
    assert "read-data=" in ini  # path section still present


def test_assemble_writes_performance_dropin(fhome, monkeypatch):
    monkeypatch.setattr(instance.systemd, "_daemon_reload", lambda: None)
    _setup(
        fhome,
        monkeypatch,
        'mods: []\nperformance:\n  cpu_affinity: "2-7"\n  nice: 5\n  memory_max: "8G"\n',
    )
    instance.assemble("main")
    dropin = instance.systemd.instance_dropin("main")
    assert dropin.exists()
    body = dropin.read_text()
    assert "CPUAffinity=2-7" in body
    assert "Nice=5" in body
    assert "MemoryMax=8G" in body


def test_create_map_builds_command(fhome, monkeypatch):
    import types

    _setup(
        fhome,
        monkeypatch,
        "mods: []\nmap_gen_settings:\n  width: 100\nseed: 42\n",
    )
    instance.assemble("main")  # seeds world.zip from the default
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(instance.subprocess, "run", fake_run)
    instance.create_map("main", force=True, seed=42)
    argv = captured["argv"]
    assert "--create" in argv
    assert "--map-gen-settings" in argv
    assert "--map-gen-seed" in argv and "42" in argv
    assert (paths.instance_dir("main") / "map-gen-settings.json").exists()


def test_create_map_refuses_existing_save(fhome, monkeypatch):
    _setup(fhome, monkeypatch, "mods: []\n")
    instance.assemble("main")  # seeds world.zip
    with pytest.raises(instance.InstanceError):
        instance.create_map("main")  # no --force


def test_backup_and_rotation(fhome):
    import os

    saves = paths.instance_saves("main")
    saves.mkdir(parents=True)
    save = saves / "world.zip"
    save.write_bytes(b"data")
    for stamp in (1_600_000_000, 1_600_000_060, 1_600_000_120):
        os.utime(save, (stamp, stamp))
        dest, _ = instance.backup("main", keep=2)
        assert dest.parent.name == "backups"
    backups = list((paths.instance_dir("main") / "backups").glob("*.zip"))
    assert len(backups) == 2  # rotation kept only the newest two


def test_backup_no_save(fhome):
    with pytest.raises(instance.InstanceError):
        instance.backup("main")


def test_new_auto_port_and_next_free(fhome):
    path_a, port_a = instance.new("alpha")
    path_b, port_b = instance.new("beta")
    assert path_a.exists() and path_b.exists()
    assert port_a == 34197 and port_b == 34198  # next free
    # the generated YAML loads and validates
    assert instance.config.load_instance("alpha")["port"] == 34197


def test_new_rejects_duplicate(fhome):
    instance.new("alpha")
    with pytest.raises(instance.InstanceError):
        instance.new("alpha")


def test_new_rejects_used_port(fhome):
    instance.new("alpha")  # takes 34197
    with pytest.raises(instance.InstanceError):
        instance.new("beta", port=34197)


def test_new_invalid_name(fhome):
    with pytest.raises(ValueError):
        instance.new("../evil")


def test_remove_deletes_everything(fhome, monkeypatch):
    monkeypatch.setattr(instance.control, "stop", lambda name: 0)
    monkeypatch.setattr(instance.control, "disable", lambda name: 0)
    monkeypatch.setattr(instance.systemd, "_daemon_reload", lambda: None)
    instance.new("main")
    inst = paths.instance_dir("main")
    (inst / "saves").mkdir()
    dropin = instance.systemd.instance_dropin("main")
    dropin.parent.mkdir(parents=True)
    dropin.write_text("[Service]\n")

    instance.remove("main")
    assert not inst.exists()
    assert not dropin.parent.exists()  # drop-in dir cleaned up too


def test_remove_missing(fhome):
    with pytest.raises(instance.InstanceError):
        instance.remove("ghost")


def test_configured_mod_names(fhome, monkeypatch):
    _setup(
        fhome,
        monkeypatch,
        "mods:\n  - name: even-distribution\n  - name: base\n  - name: FNEI\n",
    )
    # builtins excluded; configured names collected across instances
    assert instance.configured_mod_names() == {"even-distribution", "FNEI"}


def test_update_mods_skips_pinned(fhome, monkeypatch):
    _setup(
        fhome,
        monkeypatch,
        "mods:\n  - name: even-distribution\n  - name: FNEI\n    version: 0.4.1\n",
    )
    # FNEI is pinned to a version the fake portal does not offer, so resolving
    # it would raise; update_mods must skip pinned mods and not touch it.
    linked = instance.update_mods("main")
    assert [m for m, _ in linked] == ["even-distribution"]
