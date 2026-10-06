import socket

import pytest
from helpers import FakeSocket

from wake_dispatch import packet
from wake_dispatch.mac import MacError, normalise_mac, normalise_secureon


@pytest.mark.parametrize(
    "raw",
    [
        "aa:bb:cc:dd:ee:01",
        "AA:BB:CC:DD:EE:01",
        "aa-bb-cc-dd-ee-01",
        "aabb.ccdd.ee01",
        "aa bb cc dd ee 01",
        "aabbccddee01",
        "  AaBbCcDdEe01  ",
        "aa:bb-cc.dd ee01",
    ],
)
def test_normalise_mac_accepts_any_separator(raw: str) -> None:
    assert normalise_mac(raw) == "aa:bb:cc:dd:ee:01"


def test_bad_length_message() -> None:
    with pytest.raises(MacError) as err:
        normalise_mac("aa:bb:cc:dd:ee")
    assert str(err.value) == "A MAC address has 12 hex digits (0-9, A-F); this one has 10."


def test_too_long_message() -> None:
    with pytest.raises(MacError, match="this one has 14"):
        normalise_mac("aa:bb:cc:dd:ee:01:02")


def test_bad_hex_message() -> None:
    with pytest.raises(MacError) as err:
        normalise_mac("aa:bb:cc:dd:ee:0g")
    assert str(err.value) == (
        "A MAC address can only contain hex digits (0-9, A-F) and separators; found 'g'."
    )


@pytest.mark.parametrize("raw", ["", "   ", None, 12])
def test_empty_message(raw: object) -> None:
    with pytest.raises(MacError) as err:
        normalise_mac(raw)
    assert str(err.value) == "Enter a MAC address."


def test_secureon_messages() -> None:
    assert normalise_secureon("AA-BB-CC-DD-EE-F0") == "aa:bb:cc:dd:ee:f0"
    with pytest.raises(MacError) as err:
        normalise_secureon("0123")
    assert str(err.value) == "A SecureOn password has 12 hex digits (0-9, A-F); this one has 4."


def test_magic_packet_is_102_bytes() -> None:
    data = packet.magic_packet("aa:bb:cc:dd:ee:01")
    assert len(data) == 102
    assert data == b"\xff" * 6 + bytes.fromhex("aabbccddee01") * 16


def test_magic_packet_with_secureon_is_108_bytes() -> None:
    data = packet.magic_packet("AA-BB-CC-DD-EE-01", "aa:bb:cc:dd:ee:f0")
    assert len(data) == 108
    assert data == b"\xff" * 6 + bytes.fromhex("aabbccddee01") * 16 + bytes.fromhex("aabbccddeef0")


def test_magic_packet_rejects_bad_mac() -> None:
    with pytest.raises(MacError):
        packet.magic_packet("nope")


def test_send_sets_broadcast_and_closes(sandbox) -> None:
    sockets = []

    def factory():
        sock = FakeSocket(sandbox["sent"])
        sockets.append(sock)
        return sock

    data = packet.magic_packet("aa:bb:cc:dd:ee:01")
    packet.send_magic_packet(data, "192.168.1.255", 9, socket_factory=factory)
    assert sandbox["sent"] == [
        {
            "data": data,
            "address": ("192.168.1.255", 9),
            "options": [(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)],
        }
    ]
    assert sockets[0].closed


def test_send_closes_socket_on_error() -> None:
    sock = FakeSocket([], fail=OSError(101, "Network is unreachable"))
    with pytest.raises(OSError):
        packet.send_magic_packet(b"x", "192.168.1.255", 9, socket_factory=lambda: sock)
    assert sock.closed
