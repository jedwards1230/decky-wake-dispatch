"""Network facts read from procfs/sysfs, plus the TCP status check.

Every path is a module-level constant read at call time (and every function
also accepts an explicit path / reader), so tests never touch the real
``/proc`` or ``/sys``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import struct
import time
from collections.abc import Awaitable, Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from wake_dispatch.log import get_logger
from wake_dispatch.mac import MacError, normalise_mac

PROC_ROUTE = "/proc/net/route"
PROC_ARP = "/proc/net/arp"
SYS_CLASS_NET = "/sys/class/net"
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"

RTF_UP = 0x1
RTF_GATEWAY = 0x2
ATF_COMPLETE = 0x2
ZERO_MAC = "00:00:00:00:00:00"

# "up" is the normal state. "unknown" is reported by drivers that don't track
# carrier (some Wi-Fi drivers, tun/VPN devices) while they pass traffic fine, so
# it counts as up. "down", "dormant", "lowerlayerdown", "notpresent", "testing"
# and an unreadable file all count as not up.
UP_STATES = frozenset({"up", "unknown"})

STATUS_TIMEOUT = 1.0
REVERSE_DNS_TIMEOUT = 0.5
NETWORK_POLL_INTERVAL = 1.0

# Reverse lookups run on their own small pool so a slow resolver can't fill the
# loop's default executor, which asyncio.open_connection needs for getaddrinfo.
RDNS_WORKERS = 4
HOSTNAME_TTL = 300.0  # seconds to remember a resolved name
MISS_TTL = 60.0  # seconds to remember that an address has no name
_rdns_pool: ThreadPoolExecutor | None = None
_hostname_cache: dict[str, tuple[str | None, float]] = {}

Reader = Callable[[str], "str | None"]


def read_text(path: str) -> str | None:
    """Return the file's text, or ``None`` if it can't be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _hex_to_ipv4(value: str) -> str:
    """Convert /proc/net/route's little-endian hex (e.g. ``0101A8C0``) to dotted quad."""
    return socket.inet_ntoa(struct.pack("<I", int(value, 16)))


def parse_routes(text: str) -> list[dict[str, Any]]:
    """Return default routes (``iface``, ``gateway``, ``metric``) from /proc/net/route text.

    Only destination ``00000000`` entries with RTF_UP and RTF_GATEWAY set are kept.
    """
    routes: list[dict[str, Any]] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 7:
            continue
        iface, destination, gateway, flags, metric = (
            fields[0],
            fields[1],
            fields[2],
            fields[3],
            fields[6],
        )
        try:
            flag_bits = int(flags, 16)
            if int(destination, 16) != 0:
                continue
            if flag_bits & (RTF_UP | RTF_GATEWAY) != (RTF_UP | RTF_GATEWAY):
                continue
            routes.append({"iface": iface, "gateway": _hex_to_ipv4(gateway), "metric": int(metric)})
        except (ValueError, struct.error, OSError):
            continue
    return routes


def interface_up(iface: str, sys_net: str | None = None, reader: Reader | None = None) -> bool:
    """True if ``/sys/class/net/<iface>/operstate`` is in ``UP_STATES``."""
    if not iface or "/" in iface or iface in (".", ".."):
        return False
    text = (reader or read_text)(os.path.join(sys_net or SYS_CLASS_NET, iface, "operstate"))
    return text is not None and text.strip().lower() in UP_STATES


def default_route(
    route_path: str | None = None, sys_net: str | None = None, reader: Reader | None = None
) -> dict[str, str] | None:
    """Return ``{iface, gateway}`` for the lowest-metric default route on an up interface."""
    read = reader or read_text
    text = read(route_path or PROC_ROUTE)
    if not text:
        return None
    candidates = [
        r for r in parse_routes(text) if interface_up(r["iface"], sys_net=sys_net, reader=read)
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda r: r["metric"])
    return {"iface": best["iface"], "gateway": best["gateway"]}


async def wait_for_network(
    timeout: float,
    *,
    probe: Callable[[], dict[str, str] | None] | None = None,
    interval: float | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, str] | None:
    """Poll ``probe`` (default ``default_route``) until it returns a route or ``timeout`` passes."""
    check = probe or default_route
    step = NETWORK_POLL_INTERVAL if interval is None else interval
    deadline = clock() + timeout
    waited = 0.0  # also bounds the loop when ``sleep`` doesn't advance ``clock`` (tests)
    while True:
        route = check()
        if route is not None:
            return route
        remaining = min(deadline - clock(), timeout - waited)
        if remaining <= 0:
            return None
        pause = min(step, remaining)
        await sleep(pause)
        waited += pause


def read_boot_id(path: str | None = None, reader: Reader | None = None) -> str | None:
    text = (reader or read_text)(path or BOOT_ID_PATH)
    if text is None:
        return None
    return text.strip() or None


def parse_arp(text: str) -> list[dict[str, str]]:
    """Return complete entries (flags & 0x2) from /proc/net/arp text, skipping zero MACs."""
    entries: list[dict[str, str]] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 6:
            continue
        ip, _hw_type, flags, mac, _mask, iface = fields[:6]
        try:
            if not int(flags, 16) & ATF_COMPLETE:
                continue
            mac = normalise_mac(mac)
        except (ValueError, MacError):
            continue
        if mac == ZERO_MAC:
            continue
        entries.append({"ip": ip, "mac": mac, "iface": iface})
    return entries


def _rdns_executor() -> ThreadPoolExecutor:
    global _rdns_pool
    if _rdns_pool is None:
        _rdns_pool = ThreadPoolExecutor(max_workers=RDNS_WORKERS, thread_name_prefix="wd-rdns")
    return _rdns_pool


def shutdown_resolver() -> None:
    """Stop the reverse-lookup pool without waiting for stuck lookups; forget cached names."""
    global _rdns_pool
    pool, _rdns_pool = _rdns_pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)
    _hostname_cache.clear()


async def reverse_lookup(
    ip: str,
    timeout: float | None = None,
    resolver: Callable[[str], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """Reverse-resolve ``ip`` on the dedicated pool; any failure or timeout -> ``None``.

    Answers (including "no name") are cached for a few minutes; a timeout is not
    cached. On timeout the pool thread may linger until the OS resolver gives up
    (lookups still queued are cancelled); the event loop is never blocked.
    """
    cached = _hostname_cache.get(ip)
    if cached is not None and cached[1] > clock():
        return cached[0]
    resolve = resolver or socket.gethostbyaddr
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_rdns_executor(), resolve, ip),
            REVERSE_DNS_TIMEOUT if timeout is None else timeout,
        )
    except TimeoutError:
        return None
    except (OSError, ValueError, UnicodeError):
        _hostname_cache[ip] = (None, clock() + MISS_TTL)
        return None
    name = result[0] if isinstance(result, tuple) else result
    name = name if isinstance(name, str) and name else None
    _hostname_cache[ip] = (name, clock() + (HOSTNAME_TTL if name else MISS_TTL))
    return name


async def neighbours(
    arp_path: str | None = None,
    reader: Reader | None = None,
    resolver: Callable[[str], Any] | None = None,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """ARP neighbours with hostnames looked up concurrently (bounded by ``timeout`` overall)."""
    text = (reader or read_text)(arp_path or PROC_ARP)
    if not text:
        return []
    entries = parse_arp(text)
    names = await asyncio.gather(
        *(reverse_lookup(e["ip"], timeout=timeout, resolver=resolver) for e in entries)
    )
    return [{**entry, "hostname": name} for entry, name in zip(entries, names, strict=True)]


Opener = Callable[[str, int], Awaitable[tuple[Any, Any]]]


async def check_status(
    host: str | None,
    port: int | None,
    timeout: float | None = None,
    opener: Opener | None = None,
) -> str:
    """TCP-connect to ``host:port``: connected -> "awake"; refused/timeout -> "asleep".

    No host or port, or a name that doesn't resolve -> "unknown".
    """
    if not host or not port:
        return "unknown"
    open_connection = opener or asyncio.open_connection
    try:
        async with asyncio.timeout(STATUS_TIMEOUT if timeout is None else timeout):
            _reader, writer = await open_connection(host, port)
    except socket.gaierror:
        return "unknown"
    except (TimeoutError, OSError):
        return "asleep"
    except (ValueError, UnicodeError):
        return "unknown"
    writer.close()
    with contextlib.suppress(OSError):
        async with asyncio.timeout(1.0):
            await writer.wait_closed()
    return "awake"


async def status_map(
    devices: Iterable[dict[str, Any]],
    ids: list[str] | None,
    timeout: float | None = None,
    opener: Opener | None = None,
) -> dict[str, str]:
    """Check every selected device concurrently; unknown ids are ignored."""
    wanted = None if ids is None else set(ids)
    selected = [d for d in devices if wanted is None or d["id"] in wanted]
    results = await asyncio.gather(
        *(
            check_status(d.get("host"), d.get("status_port"), timeout=timeout, opener=opener)
            for d in selected
        ),
        return_exceptions=True,
    )
    out: dict[str, str] = {}
    for device, result in zip(selected, results, strict=True):
        if isinstance(result, BaseException):
            get_logger().warning("Status check for %s failed: %r", device["id"], result)
            result = "unknown"
        out[device["id"]] = result
    return out
