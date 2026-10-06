"""Test harness: install a stub ``decky`` module before ``main`` is imported."""

from __future__ import annotations

import logging
import socket
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers import FakeSocket

emitted: list[tuple[str, tuple[Any, ...]]] = []


async def _emit(event: str, *args: Any) -> None:
    emitted.append((event, args))


_decky = types.ModuleType("decky")
_decky.DECKY_PLUGIN_SETTINGS_DIR = ""
_decky.DECKY_PLUGIN_RUNTIME_DIR = ""
_decky.DECKY_PLUGIN_LOG_DIR = ""
_decky.logger = logging.getLogger("decky-test")
_decky.emit = _emit
_decky.emitted = emitted
sys.modules["decky"] = _decky


@pytest.fixture(autouse=True)
def decky_env(tmp_path: Path) -> Iterator[types.ModuleType]:
    """Point the plugin dirs at a fresh tmp_path and clear the emit log."""
    dirs = {
        "DECKY_PLUGIN_SETTINGS_DIR": tmp_path / "settings",
        "DECKY_PLUGIN_RUNTIME_DIR": tmp_path / "runtime",
        "DECKY_PLUGIN_LOG_DIR": tmp_path / "logs",
    }
    for name, path in dirs.items():
        path.mkdir()
        setattr(_decky, name, str(path))
    emitted.clear()
    yield _decky
    emitted.clear()


@pytest.fixture(autouse=True)
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Keep every test off the real /proc, /sys and network.

    procfs/sysfs paths point into ``tmp_path/fake`` (initially empty, i.e. no
    route, no ARP entries, no boot id) and the UDP socket factory is a recorder.
    """
    from wake_dispatch import netinfo, packet

    fake = tmp_path / "fake"
    (fake / "sys-net").mkdir(parents=True)
    monkeypatch.setattr(netinfo, "PROC_ROUTE", str(fake / "route"))
    monkeypatch.setattr(netinfo, "PROC_ARP", str(fake / "arp"))
    monkeypatch.setattr(netinfo, "SYS_CLASS_NET", str(fake / "sys-net"))
    monkeypatch.setattr(netinfo, "BOOT_ID_PATH", str(fake / "boot_id"))
    # shutdown_resolver() (run after every test, and by Plugin._unload) closes the
    # resolver for good; monkeypatch restores it to open for the next test.
    monkeypatch.setattr(netinfo, "_resolver_closed", False)
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(packet, "make_socket", lambda: FakeSocket(sent))
    yield {"fake": fake, "sent": sent}
    netinfo.shutdown_resolver()


@pytest.fixture(autouse=True)
def no_real_dns(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any real name lookup unless the test is marked ``real_dns``.

    Numeric 127.0.0.1 connects still work (asyncio skips getaddrinfo for literal
    addresses, and the guard lets loopback through anyway).
    """
    if request.node.get_closest_marker("real_dns"):
        return
    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host in (None, "127.0.0.1"):
            return real_getaddrinfo(host, *args, **kwargs)
        raise AssertionError(f"test made a real getaddrinfo call for {host!r}")

    def guarded_gethostbyaddr(ip: str) -> Any:
        raise AssertionError(f"test made a real reverse lookup for {ip!r}")

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyaddr", guarded_gethostbyaddr)
