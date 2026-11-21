"""Wake-on-LAN magic packets."""

from __future__ import annotations

import socket

from sshm.core.models import normalize_mac


def magic_packet(mac: str) -> bytes:
    raw = normalize_mac(mac).replace(":", "")
    if not raw:
        raise ValueError("No MAC address configured")
    return bytes.fromhex("FF" * 6 + raw * 16)


def wake(mac: str, broadcast: str = "255.255.255.255") -> None:
    """Send the packet to UDP ports 9 and 7 (both are commonly used)."""
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            sock.sendto(packet, (broadcast, port))
