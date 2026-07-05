import pytest

from factorio_server_manager import binary, cli


def test_targets_explicit_single():
    assert cli._game_version_targets("1.1") == ["1.1"]


def test_targets_all_expands_both_channels(monkeypatch):
    monkeypatch.setattr(
        binary,
        "channel_game_versions",
        lambda: {"stable": "2.0.77", "experimental": "2.1.9"},
    )
    assert cli._game_version_targets("all") == ["2.0.77", "2.1.9"]


def test_targets_all_dedupes_same_major_minor(monkeypatch):
    # both channels on the same major.minor collapse to one target
    monkeypatch.setattr(
        binary,
        "channel_game_versions",
        lambda: {"stable": "2.0.77", "experimental": "2.0.80"},
    )
    assert cli._game_version_targets("all") == ["2.0.77"]


def test_targets_default_uses_current_build(fhome, monkeypatch):
    monkeypatch.setattr(binary, "current_version", lambda: "1.1.110")
    assert cli._game_version_targets(None) == ["1.1.110"]


def test_targets_default_without_build_errors(fhome, monkeypatch):
    monkeypatch.setattr(binary, "current_version", lambda: None)
    with pytest.raises(ValueError):
        cli._game_version_targets(None)


def test_version_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert "fsm" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv,handler",
    [
        (["binary", "install"], "_cmd_binary_install"),
        (["binary", "update"], "_cmd_binary_update"),
        (["instance", "new", "x"], "_cmd_instance_new"),
        (["instance", "assemble", "x"], "_cmd_instance_assemble"),
        (["instance", "remove", "x"], "_cmd_instance_remove"),
        (["instance", "create-map", "x"], "_cmd_instance_create_map"),
        (["mods", "refresh"], "_cmd_mods_refresh"),
        (["mods", "download", "m"], "_cmd_mods_download"),
        (["show", "versions"], "_cmd_show_versions"),
        (["systemd", "install-timers"], "_cmd_systemd_install_timers"),
        (["rcon", "x", "/players"], "_cmd_rcon"),
        (["backup", "x"], "_cmd_backup"),
        (["doctor"], "_cmd_doctor"),
        (["start", "x"], None),  # start dispatches to a generated control handler
    ],
)
def test_dispatch_wiring(argv, handler):
    args = cli.build_parser().parse_args(argv)
    assert callable(args.func)
    if handler is not None:
        assert args.func is getattr(cli, handler)


def test_remove_requires_force(capsys):
    args = cli.build_parser().parse_args(["instance", "remove", "x"])
    assert args.func(args) == 1  # refused without --force
    assert "--force" in capsys.readouterr().err


def test_doctor_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.doctor, "run", lambda online=False: [cli.doctor.Check("x", "fail", "d")]
    )
    args = cli.build_parser().parse_args(["doctor"])
    assert args.func(args) == 1  # a failing check -> non-zero exit

