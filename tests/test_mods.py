import json

import pytest
from helpers import FakeResponse

from factorio_server_manager import mods, paths


def _info(name):
    return {
        "name": name,
        "releases": [
            {
                "version": "0.4.1",
                "download_url": f"/download/{name}/aaa",
                "info_json": {"factorio_version": "1.1"},
            },
            {
                "version": "0.4.10",
                "download_url": f"/download/{name}/bbb",
                "info_json": {"factorio_version": "1.1"},
            },
            {
                "version": "1.0.0",
                "download_url": f"/download/{name}/ccc",
                "info_json": {"factorio_version": "2.0"},
            },
        ],
    }


def test_select_release_unpinned_matches_build():
    release = mods.select_release(_info("m"), "1.1.110", None)
    assert release["version"] == "0.4.10"


def test_select_release_pinned():
    release = mods.select_release(_info("m"), "1.1.110", "0.4.1")
    assert release["version"] == "0.4.1"


def test_select_release_no_match():
    with pytest.raises(mods.ModError):
        mods.select_release(_info("m"), "0.17.0", None)


def test_select_release_pinned_missing():
    with pytest.raises(mods.ModError):
        mods.select_release(_info("m"), "1.1.110", "9.9.9")


def test_select_release_pinned_incompatible_warns(capsys):
    # pinned 0.4.1 targets Factorio 1.1, but the build is 2.0 -> warn, still return
    release = mods.select_release(_info("m"), "2.0.7", "0.4.1")
    assert release["version"] == "0.4.1"
    assert "may fail to load" in capsys.readouterr().err


def test_select_release_pinned_compatible_no_warn(capsys):
    mods.select_release(_info("m"), "1.1.110", "0.4.1")
    assert capsys.readouterr().err == ""


def test_ensure_cached_downloads_once(fhome, monkeypatch):
    calls = []

    def fake_urlopen(url, **kwargs):
        calls.append(url)
        return FakeResponse(b"ZIPDATA")

    monkeypatch.setattr(mods.net, "urlopen", fake_urlopen)
    release = {"version": "0.4.10", "download_url": "/download/m/bbb"}
    creds = {"username": "u", "token": "t"}

    path = mods.ensure_cached("m", release, creds)
    assert path.read_bytes() == b"ZIPDATA"
    assert "username=u" in calls[0] and "token=t" in calls[0]

    # second call is a no-op (no new download)
    mods.ensure_cached("m", release, creds)
    assert len(calls) == 1


def test_link_into_instance_swaps_versions(fhome):
    mods.cache_path("m", "0.4.1").parent.mkdir(parents=True)
    mods.cache_path("m", "0.4.1").write_bytes(b"a")
    mods.cache_path("m", "0.4.10").write_bytes(b"b")

    first = mods.link_into_instance("main", "m", "0.4.1")
    assert first.name == "m_0.4.1.zip"

    second = mods.link_into_instance("main", "m", "0.4.10")
    links = list(paths.instance_mods("main").glob("m_*.zip"))
    assert links == [second]  # old link removed, only new remains
    assert second.resolve() == mods.cache_path("m", "0.4.10")


def test_write_mod_list_enables_base(fhome):
    mods.write_mod_list("main", ["FNEI", "even-distribution"])
    data = json.loads((paths.instance_mods("main") / "mod-list.json").read_text())
    names = [m["name"] for m in data["mods"]]
    assert names[0] == "base"
    assert set(names) == {"base", "FNEI", "even-distribution"}


def test_cached_versions_sorted(fhome):
    for version in ("0.4.1", "0.4.10", "0.4.2"):
        mods.cache_path("m", version).parent.mkdir(parents=True, exist_ok=True)
        mods.cache_path("m", version).write_bytes(b"x")
    assert mods.cached_versions("m") == ["0.4.10", "0.4.2", "0.4.1"]


def test_sync_instance_skips_builtins_and_pinned(fhome, monkeypatch):
    monkeypatch.setattr(mods, "fetch_mod_info", _info)
    monkeypatch.setattr(
        mods,
        "ensure_cached",
        lambda mod, rel, creds: _fake_cache(mod, rel["version"]),
    )
    config = [
        {"name": "base"},
        {"name": "even-distribution"},
        {"name": "FNEI", "version": "0.4.1"},
    ]
    linked = mods.sync_instance("main", config, "1.1.110", {"username": "u", "token": "t"})
    assert ("even-distribution", "0.4.10") in linked
    assert ("FNEI", "0.4.1") in linked
    assert all(mod != "base" for mod, _ in linked)

    # unpinned_only skips the pinned mod
    linked2 = mods.sync_instance(
        "main", config, "1.1.110", {"username": "u", "token": "t"}, unpinned_only=True
    )
    assert [m for m, _ in linked2] == ["even-distribution"]


def _fake_cache(mod, version):
    path = mods.cache_path(mod, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"zip")
    return path


def test_ensure_cached_verifies_sha1(fhome, monkeypatch):
    import hashlib

    monkeypatch.setattr(
        mods.net, "urlopen", lambda url, **kw: FakeResponse(b"ZIPDATA")
    )
    good = {
        "version": "1.0.0",
        "download_url": "/download/m/x",
        "sha1": hashlib.sha1(b"ZIPDATA").hexdigest(),
    }
    path = mods.ensure_cached("m", good, {"username": "u", "token": "t"})
    assert path.exists()


def test_ensure_cached_rejects_bad_sha1(fhome, monkeypatch):
    monkeypatch.setattr(
        mods.net, "urlopen", lambda url, **kw: FakeResponse(b"ZIPDATA")
    )
    bad = {"version": "1.0.0", "download_url": "/download/m/x", "sha1": "0" * 40}
    with pytest.raises(mods.ModError):
        mods.ensure_cached("m", bad, {"username": "u", "token": "t"})
    assert not mods.cache_path("m", "1.0.0").exists()
    # the partial download is cleaned up, not left behind
    assert not mods.cache_path("m", "1.0.0").with_suffix(".zip.part").exists()


def test_split_mod_filename():
    assert mods.split_mod_filename("even-distribution_1.2.3.zip") == (
        "even-distribution",
        "1.2.3",
    )
    assert mods.split_mod_filename("some_mod_0.4.10.zip") == ("some_mod", "0.4.10")
    assert mods.split_mod_filename("mod-list.json") == (None, None)
    assert mods.split_mod_filename("nover.zip") == (None, None)


def test_required_dependencies_filters_prefixes():
    release = {
        "info_json": {
            "dependencies": [
                "base >= 1.1.0",
                "needed-mod >= 2.0",
                "~ loadorder-mod",
                "? optional-mod",
                "(?) hidden-mod",
                "! incompatible-mod",
            ]
        }
    }
    deps = mods.required_dependencies(release)
    assert "needed-mod" in deps
    assert "loadorder-mod" in deps
    assert "base" not in deps  # builtin
    assert "optional-mod" not in deps
    assert "hidden-mod" not in deps
    assert "incompatible-mod" not in deps


def test_resolve_closure_pulls_dependencies(fhome, monkeypatch):
    catalog = {
        "parent": {
            "name": "parent",
            "releases": [
                {
                    "version": "1.0.0",
                    "download_url": "/download/parent/x",
                    "info_json": {
                        "factorio_version": "1.1",
                        "dependencies": ["child >= 1.0"],
                    },
                }
            ],
        },
        "child": {
            "name": "child",
            "releases": [
                {
                    "version": "2.0.0",
                    "download_url": "/download/child/x",
                    "info_json": {"factorio_version": "1.1", "dependencies": []},
                }
            ],
        },
    }
    monkeypatch.setattr(mods, "fetch_mod_info", lambda name: catalog[name])
    resolved = mods.resolve_closure([{"name": "parent"}], "1.1.110")
    assert set(resolved) == {"parent", "child"}


def _catalog_with_dep():
    return {
        "parent": {
            "name": "parent",
            "releases": [
                {
                    "version": "1.0.0",
                    "download_url": "/download/parent/x",
                    "info_json": {
                        "factorio_version": "1.1",
                        "dependencies": ["child >= 1.0"],
                    },
                }
            ],
        },
        "child": {
            "name": "child",
            "releases": [
                {
                    "version": "2.0.0",
                    "download_url": "/download/child/x",
                    "info_json": {"factorio_version": "1.1", "dependencies": []},
                }
            ],
        },
    }


def test_download_caches_mod_and_deps(fhome, monkeypatch):
    catalog = _catalog_with_dep()
    monkeypatch.setattr(mods, "fetch_mod_info", lambda name: catalog[name])
    monkeypatch.setattr(
        mods, "ensure_cached", lambda mod, rel, creds: _fake_cache(mod, rel["version"])
    )
    cached = mods.download("parent", "1.1.110", {"username": "u", "token": "t"})
    assert ("parent", "1.0.0") in cached
    assert ("child", "2.0.0") in cached  # dependency pulled too
    assert mods.cache_path("child", "2.0.0").exists()


def test_refresh_adds_latest_keeps_old(fhome, monkeypatch):
    _fake_cache("m", "1.0.0")  # an old version already cached
    monkeypatch.setattr(
        mods,
        "fetch_mod_info",
        lambda name: {
            "name": name,
            "releases": [
                {
                    "version": "1.0.0",
                    "download_url": f"/download/{name}/a",
                    "info_json": {"factorio_version": "1.1", "dependencies": []},
                },
                {
                    "version": "1.1.0",
                    "download_url": f"/download/{name}/b",
                    "info_json": {"factorio_version": "1.1", "dependencies": []},
                },
            ],
        },
    )
    monkeypatch.setattr(
        mods, "ensure_cached", lambda mod, rel, creds: _fake_cache(mod, rel["version"])
    )
    added = mods.refresh("1.1.110", {"username": "u", "token": "t"})
    assert added == [("m", "1.1.0")]
    assert mods.cached_versions("m") == ["1.1.0", "1.0.0"]  # old retained


def test_refresh_includes_extra_mods(fhome, monkeypatch):
    # nothing cached yet; a configured-but-uncached mod is passed via extra_mods
    monkeypatch.setattr(
        mods,
        "fetch_mod_info",
        lambda name: {
            "name": name,
            "releases": [
                {
                    "version": "1.0.0",
                    "download_url": f"/download/{name}/x",
                    "info_json": {"factorio_version": "1.1", "dependencies": []},
                }
            ],
        },
    )
    monkeypatch.setattr(
        mods, "ensure_cached", lambda mod, rel, creds: _fake_cache(mod, rel["version"])
    )
    added = mods.refresh(
        "1.1.110", {"username": "u", "token": "t"}, extra_mods={"new-mod", "base"}
    )
    assert ("new-mod", "1.0.0") in added
    assert mods.cache_path("new-mod", "1.0.0").exists()


def test_refresh_skips_incompatible(fhome, monkeypatch):
    _fake_cache("m", "1.0.0")
    # portal only has a release for a different game version
    monkeypatch.setattr(
        mods,
        "fetch_mod_info",
        lambda name: {
            "name": name,
            "releases": [
                {
                    "version": "2.0.0",
                    "download_url": f"/download/{name}/x",
                    "info_json": {"factorio_version": "2.0", "dependencies": []},
                }
            ],
        },
    )
    assert mods.refresh("1.1.110", {"username": "u", "token": "t"}) == []


def test_describe(fhome, monkeypatch):
    _fake_cache("m", "1.0.0")
    monkeypatch.setattr(
        mods,
        "fetch_mod_info",
        lambda name: {
            "name": "m",
            "title": "Mod M",
            "releases": [
                {
                    "version": "1.0.0",
                    "download_url": "/d",
                    "info_json": {
                        "factorio_version": "1.1",
                        "dependencies": ["needed >= 1.0"],
                    },
                },
                {
                    "version": "2.0.0",
                    "download_url": "/d",
                    "info_json": {"factorio_version": "2.0", "dependencies": []},
                },
            ],
        },
    )
    summary = mods.describe("m", ["1.1.110", "2.0.5"])
    assert summary["latest"] == "2.0.0"
    assert summary["picks"] == {"1.1.110": "1.0.0", "2.0.5": "2.0.0"}
    assert summary["dependencies"] == ["needed"]
    assert summary["cached"] == ["1.0.0"]


def test_ensure_cached_records_game_version(fhome, monkeypatch):
    monkeypatch.setattr(
        mods.net, "urlopen", lambda url, **kw: FakeResponse(b"ZIPDATA")
    )
    release = {
        "version": "2.1.0",
        "download_url": "/download/m/x",
        "info_json": {"factorio_version": "2.1"},
    }
    mods.ensure_cached("m", release, {"username": "u", "token": "t"})
    assert mods.factorio_version_of("m", "2.1.0") == "2.1"


def test_download_all_channels_caches_both_variants(fhome, monkeypatch):
    # one release per game version; 'all' should cache both, each tagged
    monkeypatch.setattr(
        mods,
        "fetch_mod_info",
        lambda name: {
            "name": name,
            "releases": [
                {
                    "version": "1.0.10",
                    "download_url": f"/download/{name}/a",
                    "info_json": {"factorio_version": "2.0", "dependencies": []},
                },
                {
                    "version": "2.1.0",
                    "download_url": f"/download/{name}/b",
                    "info_json": {"factorio_version": "2.1", "dependencies": []},
                },
            ],
        },
    )

    def fake_cache(mod, rel, creds):
        path = _fake_cache(mod, rel["version"])
        mods._record_metadata(mod, rel)  # real recording path
        return path

    monkeypatch.setattr(mods, "ensure_cached", fake_cache)
    creds = {"username": "u", "token": "t"}
    # simulate 'all' expanding to both channel game versions
    for gv in ("2.0.77", "2.1.9"):
        mods.download("m", gv, creds)
    assert mods.factorio_version_of("m", "1.0.10") == "2.0"
    assert mods.factorio_version_of("m", "2.1.0") == "2.1"
    assert mods.cached_versions("m") == ["2.1.0", "1.0.10"]


def test_sync_instance_prunes_removed_mods(fhome, monkeypatch):
    monkeypatch.setattr(
        mods,
        "fetch_mod_info",
        lambda name: {
            "name": name,
            "releases": [
                {
                    "version": "1.0.0",
                    "download_url": f"/download/{name}/x",
                    "info_json": {"factorio_version": "1.1", "dependencies": []},
                }
            ],
        },
    )
    monkeypatch.setattr(
        mods, "ensure_cached", lambda mod, rel, creds: _fake_cache(mod, rel["version"])
    )
    creds = {"username": "u", "token": "t"}
    mods.sync_instance("main", [{"name": "keep"}, {"name": "drop"}], "1.1.110", creds)
    assert (paths.instance_mods("main") / "drop_1.0.0.zip").exists()

    # re-sync without 'drop': its link must be pruned, 'keep' retained
    mods.sync_instance("main", [{"name": "keep"}], "1.1.110", creds)
    assert (paths.instance_mods("main") / "keep_1.0.0.zip").exists()
    assert not (paths.instance_mods("main") / "drop_1.0.0.zip").exists()
