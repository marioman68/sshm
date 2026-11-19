"""Minecraft Java Edition "Server List Ping" — players, version and MOTD.

Implements the handshake + status request from the public protocol spec
(https://wiki.vg/Server_List_Ping) using only the standard library.
"""

from __future__ import annotations

import json
import re
import socket
import struct
import time
from dataclasses import dataclass, field


@dataclass
class MinecraftStatus:
    online: int
    max_players: int
    version: str
    motd: str
    latency_ms: float
    players: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{self.online}/{self.max_players} players · {self.version}"


def _varint(n: int) -> bytes:
    out = b""
    n &= 0xFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        out += struct.pack("B", b | (0x80 if n else 0))
        if not n:
            return out


def _read_varint(sock: socket.socket) -> int:
    num, shift = 0, 0
    for _ in range(5):
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("connection closed")
        val = byte[0]
        num |= (val & 0x7F) << shift
        if not val & 0x80:
            return num
        shift += 7
    raise ValueError("varint too long")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return buf


def _flatten_motd(desc) -> str:
    if isinstance(desc, str):
        text = desc
    elif isinstance(desc, dict):
        text = desc.get("text", "") + "".join(_flatten_motd(x) for x in desc.get("extra", []))
    elif isinstance(desc, list):
        text = "".join(_flatten_motd(x) for x in desc)
    else:
        text = ""
    return re.sub(r"§.", "", text)


def ping(host: str, port: int = 25565, timeout: float = 2.0) -> MinecraftStatus:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        hostb = host.encode()
        handshake = b"\x00" + _varint(767) + _varint(len(hostb)) + hostb + struct.pack(">H", port) + _varint(1)
        sock.sendall(_varint(len(handshake)) + handshake)
        t0 = time.monotonic()
        sock.sendall(b"\x01\x00")  # status request
        _length = _read_varint(sock)
        if _read_varint(sock) != 0:
            raise ValueError("unexpected packet")
        size = _read_varint(sock)
        data = json.loads(_recv_exact(sock, size).decode("utf-8", "replace"))
        latency = (time.monotonic() - t0) * 1000
    players = data.get("players", {}) if isinstance(data, dict) else {}
    sample = [p.get("name", "") for p in players.get("sample", []) or [] if isinstance(p, dict)]
    return MinecraftStatus(
        online=int(players.get("online", 0)),
        max_players=int(players.get("max", 0)),
        version=str((data.get("version") or {}).get("name", "?")),
        motd=_flatten_motd(data.get("description", "")).strip()[:120],
        latency_ms=latency,
        players=[n for n in sample if n][:12],
    )
