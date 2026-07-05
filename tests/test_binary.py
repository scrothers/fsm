import io
import tarfile

import pytest
from helpers import FakeResponse, headless_tarball, make_build

from factorio_server_manager import binary, paths


def test_installed_versions_newest_first(fhome):
    make_build(fhome, "1.1.19")
    make_build(fhome, "1.1.110")
    assert binary.installed_versions() == ["1.1.110", "1.1.19"]


def test_current_version(fhome):
    make_build(fhome, "1.1.110", current=True)
    assert binary.current_version() == "1.1.110"


def test_set_current(fhome):
    make_build(fhome, "1.1.110")
    make_build(fhome, "1.1.19")
    binary.set_current("1.1.19")
    assert binary.current_version() == "1.1.19"
    binary.set_current("1.1.110")
    assert binary.current_version() == "1.1.110"


def test_set_current_missing(fhome):
    with pytest.raises(binary.BinaryError):
        binary.set_current("9.9.9")


def test_install_extracts_and_reads_version(fhome, monkeypatch):
    data = headless_tarball("1.1.110")
    monkeypatch.setattr(
        binary.net, "urlopen", lambda url, **kw: FakeResponse(data)
    )
    version = binary.install("latest")
    assert version == "1.1.110"
    assert paths.binary_path(paths.build_dir("1.1.110")).exists()
    # first install with no current becomes current automatically
    assert binary.current_version() == "1.1.110"


def test_install_is_idempotent(fhome, monkeypatch):
    data = headless_tarball("1.1.110")
    monkeypatch.setattr(
        binary.net, "urlopen", lambda url, **kw: FakeResponse(data)
    )
    binary.install("1.1.110")
    binary.install("1.1.110")  # second call must not raise
    assert binary.installed_versions() == ["1.1.110"]


class _FakeTar:
    """Records extractall() kwargs; yields one benign member."""

    def __init__(self):
        self.kwargs = None

    def getmembers(self):
        return [tarfile.TarInfo("factorio/info.json")]

    def extractall(self, dest, **kwargs):
        self.kwargs = kwargs


def test_safe_extract_uses_data_filter_when_available(monkeypatch, tmp_path):
    # Force data_filter present (so this holds even on Python 3.11.2) -> filter="data".
    monkeypatch.setattr(binary.tarfile, "data_filter", object(), raising=False)
    tar = _FakeTar()
    binary._safe_extract(tar, tmp_path)
    assert tar.kwargs.get("filter") == "data"


def test_safe_extract_falls_back_without_filter(monkeypatch, tmp_path):
    # Python < 3.11.4 (Debian 12's 3.11.2): no data_filter -> plain extractall.
    monkeypatch.delattr(binary.tarfile, "data_filter", raising=False)
    tar = _FakeTar()
    binary._safe_extract(tar, tmp_path)
    assert "filter" not in tar.kwargs  # plain extract, no unsupported kwarg


def test_safe_extract_rejects_traversal(fhome, monkeypatch, tmp_path):
    # Force the manual-validation fallback and feed it an escaping member.
    monkeypatch.delattr(binary.tarfile, "data_filter", raising=False)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    buffer.seek(0)
    with tarfile.open(fileobj=buffer) as tar:
        with pytest.raises(binary.BinaryError):
            binary._safe_extract(tar, tmp_path)


def test_install_channel_token_sets_symlink(fhome, monkeypatch):
    data = headless_tarball("1.1.110")
    monkeypatch.setattr(
        binary.net, "urlopen", lambda url, **kw: FakeResponse(data)
    )
    binary.install("experimental")
    chans = binary.channels()
    assert chans["experimental"] == "1.1.110"
    assert chans["current"] == "1.1.110"  # first install becomes current
    assert "stable" not in chans


def test_install_concrete_does_not_set_channel(fhome, monkeypatch):
    data = headless_tarball("1.1.110")
    monkeypatch.setattr(
        binary.net, "urlopen", lambda url, **kw: FakeResponse(data)
    )
    binary.install("1.1.110")
    assert binary.channels() == {"current": "1.1.110"}


def test_installed_versions_ignores_channel_symlinks(fhome, monkeypatch):
    make_build(fhome, "1.1.110")
    (fhome / "server" / "stable").symlink_to("factorio_1.1.110")
    # the symlink must not appear as its own build
    assert binary.installed_versions() == ["1.1.110"]


def test_update_refreshes_opted_in_channels(fhome, monkeypatch):
    make_build(fhome, "1.1.110")
    (fhome / "server" / "stable").symlink_to("factorio_1.1.110")

    monkeypatch.setattr(
        binary,
        "latest_releases",
        lambda: {
            "stable": {"headless": "1.1.111"},
            "experimental": {"headless": "2.0.7"},
        },
    )

    def fake_install(version, **kw):
        make_build(fhome, version)
        return version

    monkeypatch.setattr(binary, "install", fake_install)

    changes = binary.update()
    assert changes == [("stable", "1.1.110", "1.1.111")]
    assert binary.channels()["stable"] == "1.1.111"
    # experimental was not opted into (no symlink) so it is left alone
    assert "experimental" not in binary.channels()


def test_update_noop_when_current(fhome, monkeypatch):
    make_build(fhome, "1.1.111")
    (fhome / "server" / "stable").symlink_to("factorio_1.1.111")
    monkeypatch.setattr(
        binary, "latest_releases", lambda: {"stable": {"headless": "1.1.111"}}
    )
    assert binary.update() == []


def test_channel_game_versions(monkeypatch):
    monkeypatch.setattr(
        binary,
        "latest_releases",
        lambda: {
            "stable": {"headless": "2.0.77"},
            "experimental": {"headless": "2.1.9"},
        },
    )
    assert binary.channel_game_versions() == {
        "stable": "2.0.77",
        "experimental": "2.1.9",
    }
