"""Minimal Source RCON client for talking to a running instance.

Factorio's headless server speaks the Source RCON protocol; this implements
just enough of it (auth + single command/response) over stdlib sockets, with no
third-party dependency. Used by ``fsm rcon`` to run console commands against a
live server (``/players``, ``/save``, ``/promote``, broadcasts, ...).
"""

from __future__ import annotations

import json
import socket
import struct

from . import paths

#: Source RCON packet types.
_AUTH = 3
_EXEC = 2
_RESPONSE_VALUE = 0
_AUTH_RESPONSE = 2

DEFAULT_TIMEOUT = 10


class RconError(Exception):
    """Raised when an RCON connection, auth or command fails."""


def _pack(request_id: int, packet_type: int, body: str) -> bytes:
    """Encode a Source RCON packet."""
    payload = (
        struct.pack("<ii", request_id, packet_type)
        + body.encode("utf-8")
        + b"\x00\x00"
    )
    return struct.pack("<i", len(payload)) + payload


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    """Read exactly ``count`` bytes or raise on a closed connection."""
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise RconError("connection closed by server")
        data += chunk
    return data


def _read_packet(sock: socket.socket) -> tuple[int, int, str]:
    """Read one Source RCON packet, returning ``(id, type, body)``."""
    (length,) = struct.unpack("<i", _recv_exact(sock, 4))
    payload = _recv_exact(sock, length)
    request_id, packet_type = struct.unpack("<ii", payload[:8])
    body = payload[8:-2].decode("utf-8", errors="replace")
    return request_id, packet_type, body


def execute(
    host: str,
    port: int,
    password: str,
    command: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Authenticate and run a single console command, returning its output.

    Large responses can span multiple RCON packets; after the first response
    packet, continuation packets are read until the server goes idle or closes,
    so long outputs are not truncated.

    :raises RconError: on connection failure, bad password, or protocol error.
    """
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise RconError(f"rcon connection to {host}:{port} failed: {exc}") from exc
    try:
        sock.settimeout(timeout)
        sock.sendall(_pack(1, _AUTH, password))
        request_id, packet_type, _ = _read_packet(sock)
        # Some servers emit an empty RESPONSE_VALUE before the auth response.
        if packet_type == _RESPONSE_VALUE:
            request_id, packet_type, _ = _read_packet(sock)
        if request_id == -1:
            raise RconError("authentication failed (bad rcon password)")
        sock.sendall(_pack(2, _EXEC, command))
        parts = [_read_packet(sock)[2]]
        # Read any continuation packets; stop when the server has nothing more to
        # send (short idle) or closes the connection.
        sock.settimeout(0.3)
        while True:
            try:
                parts.append(_read_packet(sock)[2])
            except (TimeoutError, RconError):
                break
        return "".join(parts)
    except OSError as exc:
        raise RconError(f"rcon error talking to {host}:{port}: {exc}") from exc
    finally:
        sock.close()


def instance_endpoint(name: str) -> tuple[str, int, str]:
    """Resolve an instance's RCON endpoint from its runtime facts.

    :returns: ``(host, port, password)`` (host is always loopback).
    :raises RconError: if the instance is not assembled or has no rcon block.
    """
    runtime_file = paths.instance_runtime(name)
    if not runtime_file.exists():
        raise RconError(f"instance not assembled: run 'fsm instance assemble {name}'")
    rcon = json.loads(runtime_file.read_text()).get("rcon")
    if not rcon:
        raise RconError(
            f"rcon not configured for '{name}'; add an rcon block to instance.yaml"
        )
    return "127.0.0.1", int(rcon["port"]), str(rcon["password"])
