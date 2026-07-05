import types

from helpers import make_build, make_credentials

from factorio_server_manager import doctor


def test_check_python_ok():
    assert doctor.check_python().status == "ok"


def test_check_credentials(fhome):
    assert doctor.check_credentials().status == "warn"  # none yet
    make_credentials(fhome)
    assert doctor.check_credentials().status == "ok"


def test_check_current_build(fhome):
    assert doctor.check_current_build().status == "warn"  # none installed
    make_build(fhome, "1.1.110", current=True)
    assert doctor.check_current_build().status == "ok"


def test_check_disk_ok(fhome, monkeypatch):
    monkeypatch.setattr(
        doctor.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=50 * 1024**3)
    )
    assert doctor.check_disk().status == "ok"


def test_check_disk_low(fhome, monkeypatch):
    monkeypatch.setattr(
        doctor.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=100 * 1024**2)
    )
    assert doctor.check_disk().status == "warn"


def test_check_systemd_running(monkeypatch):
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="running\n", stderr=""),
    )
    assert doctor.check_systemd().status == "ok"


def test_check_systemd_absent(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(doctor.subprocess, "run", boom)
    assert doctor.check_systemd().status == "warn"


def test_check_cgroup_and_linger_do_not_crash(fhome):
    # Environment-dependent; must return a Check regardless of platform.
    assert isinstance(doctor.check_cgroup_delegation(), doctor.Check)
    assert isinstance(doctor.check_linger(), doctor.Check)


def test_run_and_render(fhome):
    results = doctor.run()
    assert all(isinstance(r, doctor.Check) for r in results)
    assert {r.name for r in results} >= {"python", "credentials", "disk"}
    text = doctor.render(results)
    assert "python" in text


def test_run_online_adds_portal(fhome, monkeypatch):
    monkeypatch.setattr(doctor, "check_portal", lambda: doctor.Check("portal", "ok", "x"))
    names = [r.name for r in doctor.run(online=True)]
    assert "portal" in names
