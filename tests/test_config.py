import pytest
from helpers import make_build, make_credentials

from factorio_server_manager import config


def _write_instance(home, text):
    path = home / "instances" / "main" / "instance.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return path


def test_load_instance_applies_defaults(fhome):
    _write_instance(fhome, "name: main\n")
    cfg = config.load_instance("main")
    assert cfg["game_version"] == "current"
    assert cfg["port"] == 34197
    assert cfg["save"] == "world.zip"
    assert cfg["mods"] == []


def test_load_instance_missing(fhome):
    with pytest.raises(config.ConfigError):
        config.load_instance("nope")


def test_resolve_build_current(fhome):
    make_build(fhome, "1.1.110", current=True)
    assert config.resolve_build("current") == "1.1.110"


def test_resolve_build_pinned(fhome):
    make_build(fhome, "1.1.110")
    assert config.resolve_build("1.1.110") == "1.1.110"


def test_resolve_build_missing(fhome):
    with pytest.raises(config.ConfigError):
        config.resolve_build("9.9.9")


def test_resolve_build_channel(fhome):
    make_build(fhome, "1.1.110")
    (fhome / "server" / "stable").symlink_to("factorio_1.1.110")
    assert config.resolve_build("stable") == "1.1.110"
    # 'latest' is an alias for the experimental channel
    (fhome / "server" / "experimental").symlink_to("factorio_1.1.110")
    assert config.resolve_build("latest") == "1.1.110"


def test_resolve_build_channel_missing(fhome):
    make_build(fhome, "1.1.110")
    with pytest.raises(config.ConfigError):
        config.resolve_build("experimental")


def test_load_credentials(fhome):
    make_credentials(fhome)
    creds = config.load_credentials()
    assert creds["username"] == "tester"
    assert creds["token"] == "deadbeef"


def test_load_credentials_missing(fhome):
    with pytest.raises(config.ConfigError):
        config.load_credentials()


def test_game_version_coerced_to_string(fhome):
    # YAML parses 2.0 as a float; it must not reach us as 2.0 or collapse a
    # trailing zero.
    _write_instance(fhome, "name: main\ngame_version: 2.0\n")
    cfg = config.load_instance("main")
    assert cfg["game_version"] == "2.0"
    assert isinstance(cfg["game_version"], str)


def test_invalid_port_rejected(fhome):
    _write_instance(fhome, "name: main\nport: 70000\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_rcon_missing_keys_rejected(fhome):
    _write_instance(fhome, "name: main\nrcon:\n  port: 27015\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_rcon_valid(fhome):
    _write_instance(
        fhome, "name: main\nrcon:\n  port: 27015\n  password: pw\n"
    )
    cfg = config.load_instance("main")
    assert cfg["rcon"]["port"] == 27015


def test_invalid_instance_name_rejected(fhome):
    with pytest.raises(config.ConfigError):
        config.load_instance("../evil")


def test_extra_args_must_be_list_of_strings(fhome):
    _write_instance(fhome, "name: main\nextra_args:\n  - 123\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_whitelist_must_be_list(fhome):
    _write_instance(fhome, "name: main\nwhitelist: alice\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_seed_must_be_int(fhome):
    _write_instance(fhome, "name: main\nseed: abc\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_map_gen_settings_must_be_mapping(fhome):
    _write_instance(fhome, "name: main\nmap_gen_settings:\n  - 1\n  - 2\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_performance_must_be_mapping(fhome):
    _write_instance(fhome, "name: main\nperformance: fast\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_performance_nice_must_be_int(fhome):
    _write_instance(fhome, "name: main\nperformance:\n  nice: high\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_performance_affinity_must_be_string(fhome):
    _write_instance(fhome, "name: main\nperformance:\n  cpu_affinity: 5\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_config_ini_must_be_mapping(fhome):
    _write_instance(fhome, "name: main\nconfig_ini: nope\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_config_ini_section_must_be_mapping(fhome):
    _write_instance(fhome, "name: main\nconfig_ini:\n  other: nope\n")
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_config_ini_value_must_be_scalar(fhome):
    _write_instance(
        fhome, "name: main\nconfig_ini:\n  other:\n    key:\n      - list\n"
    )
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_config_ini_rejects_newline_injection(fhome):
    _write_instance(
        fhome, 'name: main\nconfig_ini:\n  other:\n    key: "v\\n[evil]"\n'
    )
    with pytest.raises(config.ConfigError):
        config.load_instance("main")


def test_yaml_name_does_not_override_directory(fhome):
    _write_instance(fhome, "name: something-else\n")
    cfg = config.load_instance("main")
    assert cfg["name"] == "main"
