from factorio_server_manager.semver import latest, major_minor, version_tuple


def test_version_tuple_orders_numerically():
    assert version_tuple("1.1.110") > version_tuple("1.1.19")


def test_major_minor():
    assert major_minor("1.1.110") == "1.1"
    assert major_minor("2.0.7") == "2.0"


def test_latest_picks_highest():
    assert latest(["0.4.1", "0.4.10", "0.4.2"]) == "0.4.10"


def test_latest_empty_is_none():
    assert latest([]) is None
