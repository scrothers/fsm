import json
import struct

import pytest

from factorio_server_manager import paths, rcon


class FakeSocket:
    """In-memory Source RCON server: echoes commands, checks the password.

    ``split`` emits the command response as two packets to exercise the
    multi-packet continuation read.
    """

    def __init__(self, password: str, *, split: bool = False):
        self.password = password
        self.split = split
        self.out = b""

    def settimeout(self, timeout):
        pass

    def sendall(self, data):
        request_id, packet_type = struct.unpack("<ii", data[4:12])
        body = data[12:-2].decode()
        if packet_type == rcon._AUTH:
            ok_id = request_id if body == self.password else -1
            self.out += rcon._pack(ok_id, 2, "")  # SERVERDATA_AUTH_RESPONSE
        elif packet_type == rcon._EXEC:
            if self.split:
                self.out += rcon._pack(request_id, rcon._RESPONSE_VALUE, "part1;")
                self.out += rcon._pack(request_id, rcon._RESPONSE_VALUE, "part2")
            else:
                self.out += rcon._pack(request_id, rcon._RESPONSE_VALUE, f"echo:{body}")

    def recv(self, count):
        chunk, self.out = self.out[:count], self.out[count:]
        return chunk

    def close(self):
        pass


def test_execute_ok(monkeypatch):
    monkeypatch.setattr(
        rcon.socket, "create_connection", lambda addr, timeout=None: FakeSocket("pw")
    )
    assert rcon.execute("h", 1, "pw", "/players") == "echo:/players"


def test_execute_reads_multi_packet_response(monkeypatch):
    monkeypatch.setattr(
        rcon.socket,
        "create_connection",
        lambda addr, timeout=None: FakeSocket("pw", split=True),
    )
    assert rcon.execute("h", 1, "pw", "/help") == "part1;part2"


def test_execute_bad_password(monkeypatch):
    monkeypatch.setattr(
        rcon.socket, "create_connection", lambda addr, timeout=None: FakeSocket("pw")
    )
    with pytest.raises(rcon.RconError):
        rcon.execute("h", 1, "wrong", "/players")


def test_execute_connection_error(monkeypatch):
    def boom(addr, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(rcon.socket, "create_connection", boom)
    with pytest.raises(rcon.RconError):
        rcon.execute("h", 1, "pw", "/players")


def _write_runtime(fhome, rcon_block):
    path = paths.instance_runtime("main")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"rcon": rcon_block}))


def test_instance_endpoint(fhome):
    _write_runtime(fhome, {"port": 27015, "password": "s"})
    assert rcon.instance_endpoint("main") == ("127.0.0.1", 27015, "s")


def test_instance_endpoint_no_rcon(fhome):
    _write_runtime(fhome, None)
    with pytest.raises(rcon.RconError):
        rcon.instance_endpoint("main")


def test_instance_endpoint_unassembled(fhome):
    with pytest.raises(rcon.RconError):
        rcon.instance_endpoint("ghost")
