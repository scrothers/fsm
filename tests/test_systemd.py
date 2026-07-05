from factorio_server_manager import systemd


def _no_reload(monkeypatch):
    monkeypatch.setattr(systemd, "_daemon_reload", lambda: None)


def test_apply_dropin_writes(fhome, monkeypatch):
    _no_reload(monkeypatch)
    path = systemd.apply_dropin("main", {"CPUAffinity": "2-7", "Nice": "5"})
    assert path is not None and path.exists()
    body = path.read_text()
    assert body.startswith("[Service]\n")
    assert "CPUAffinity=2-7" in body
    assert "Nice=5" in body


def test_apply_dropin_removes_when_empty(fhome, monkeypatch):
    _no_reload(monkeypatch)
    systemd.apply_dropin("main", {"Nice": "5"})
    assert systemd.instance_dropin("main").exists()
    assert systemd.apply_dropin("main", {}) is None
    assert not systemd.instance_dropin("main").exists()


def test_install_writes_unit(fhome, monkeypatch):
    _no_reload(monkeypatch)
    target = systemd.install()
    assert target.name == "factorio@.service"
    assert "ExecStart" in target.read_text()


def test_remove_dropin_cleans_empty_dir(fhome, monkeypatch):
    _no_reload(monkeypatch)
    systemd.apply_dropin("main", {"Nice": "5"})
    dropin = systemd.instance_dropin("main")
    assert dropin.parent.exists()
    systemd.remove_dropin("main")
    assert not dropin.exists()
    assert not dropin.parent.exists()  # empty .d dir removed


def test_install_timers(fhome, monkeypatch):
    calls = []
    monkeypatch.setattr(systemd, "_systemctl", lambda *a: calls.append(a))
    installed = systemd.install_timers()
    names = {p.name for p in installed}
    assert names == set(systemd.TIMER_UNITS)
    for path in installed:
        assert path.exists()
    # both timers were enabled
    enabled = [a for a in calls if a[:2] == ("enable", "--now")]
    assert {a[2] for a in enabled} == {"fsm-mods-refresh.timer", "fsm-binary-update.timer"}
