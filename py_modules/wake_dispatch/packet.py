"""Wake-on-LAN magic packets and UDP broadcast sending."""

from __future__ import annotations

import socket
from typing import Any, Protocol

from wake_dispatch.mac import normalise_mac, normalise_secureon, to_bytes

SYNC_STREAM = b"\xff" * 6
MAC_REPEATS = 16


class DatagramSocket(Protocol):
    def setsockopt(self, level: int, option: int, value: int) -> Any: ...
    def sendto(self, data: bytes, address: tuple[str, int]) -> int: ...
    def close(self) -> None: ...


def magic_packet(mac: str, secureon: str | None = None) -> bytes:
    """Build the packet: 6 x 0xFF, the MAC 16 times, then the optional SecureOn password.

    102 bytes without SecureOn, 108 bytes with it.
    """
    payload = SYNC_STREAM + to_bytes(normalise_mac(mac)) * MAC_REPEATS
    if secureon:
        payload += to_bytes(normalise_secureon(secureon))
    return payload


def make_socket() -> DatagramSocket:
    """Default socket factory: a plain IPv4 UDP socket (replaced in tests)."""
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_magic_packet(packet: bytes, broadcast: str, port: int, socket_factory=None) -> None:
    """Send ``packet`` once to ``(broadcast, port)`` with SO_BROADCAST enabled.

    ``socket_factory`` defaults to this module's ``make_socket`` looked up at call
    time, so tests can patch it. Raises ``OSError`` on failure.
    """
    factory = socket_factory or make_socket
    sock = factory()
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    finally:
        sock.close()
