import types

import pytest

from factorio_server_manager import control


@pytest.fixture
def captured(monkeypatch):
    """Capture the argv/kwargs of every subprocess the control wrappers run."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(control.subprocess, "run", fake_run)
    return calls


@pytest.mark.parametrize(
    "func,verb",
    [
        (control.start, "start"),
        (control.stop, "stop"),
        (control.enable, "enable"),
        (control.disable, "disable"),
        (control.status, "status"),
    ],
)
def test_systemctl_wrappers(captured, func, verb):
    assert func("main") == 0
    args, kwargs = captured[-1]
    assert args == ["systemctl", "--user", verb, "factorio@main"]
    assert kwargs["env"].get("XDG_RUNTIME_DIR")  # set so --user works over ssh


def test_logs_plain(captured):
    control.logs("main")
    args, _ = captured[-1]
    assert args == ["journalctl", "--user", "-u", "factorio@main"]


def test_logs_follow(captured):
    control.logs("main", follow=True)
    args, _ = captured[-1]
    assert args[-1] == "-f"
