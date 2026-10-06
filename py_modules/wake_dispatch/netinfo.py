"""Network facts read from procfs/sysfs, name lookups, and the TCP status check.

Every path is a module-level constant read at call time (and every function
also accepts an explicit path / reader), so tests never touch the real
``/proc`` or ``/sys``.

Blocking name lookups (``getaddrinfo``, ``gethostbyaddr``) never run on a
``ThreadPoolExecutor``, not even the loop's default one: at interpreter exit
``concurrent.futures`` joins every executor worker, so one hung lookup would
keep the process alive until Decky kills it. Each lookup gets its own daemon
thread instead (bounded by ``LOOKUP_THREADS``), and the status check resolves
the host itself and connects to the numeric address so asyncio never calls
``getaddrinfo`` on its default executor.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import ipaddress
import os
import socket
import struct
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from wake_dispatch.devices import HOST_MAX, sanitise_name
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

STATUS_TIMEOUT = 1.0  # TCP connect, per device
STATUS_LOOKUP_TIMEOUT = 1.0  # resolving a status host name, per device
REVERSE_DNS_TIMEOUT = 0.5
NETWORK_POLL_INTERVAL = 1.0

# At most this many lookup threads at once; a lookup that finds no free slot
# fails fast (-> None) instead of queueing behind stuck ones.
LOOKUP_THREADS = 8
HOSTNAME_TTL = 300.0  # seconds to remember a resolved name
MISS_TTL = 60.0  # seconds to remember that an address has no name
ADDRESS_TTL = 30.0  # seconds to remember a status host's address
ADDRESS_MISS_TTL = 10.0  # seconds to remember that a status host doesn't resolve

# Connect errors that mean "this device has no route there", not "the PC is off".
NO_ROUTE_ERRNOS = frozenset(
    {errno.ENETUNREACH, errno.ENETDOWN, errno.EADDRNOTAVAIL, errno.EHOSTUNREACH}
)

_lookup_slots = threading.BoundedSemaphore(LOOKUP_THREADS)
_resolver_closed = False
_hostname_cache: dict[str, tuple[str | None, float]] = {}
_address_cache: dict[str, tuple[str | None, float]] = {}
_now: Callable[[], float] = time.monotonic  # clock for the address cache

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


_OK, _FAILED, _TIMED_OUT = "ok", "failed", "timed out"


async def _lookup_in_thread(
    func: Callable[[str], Any], arg: str, timeout: float
) -> tuple[str, Any]:
    """Run blocking ``func(arg)`` on a daemon thread; return ``(outcome, value)``.

    ``outcome`` is ``_OK`` (value = the result), ``_FAILED`` (value = the
    exception) or ``_TIMED_OUT`` (also used when the resolver is shut down or
    every lookup slot is taken). The result comes back through
    ``loop.call_soon_threadsafe``; a thread that finishes after the caller gave
    up, or after the loop closed, just drops it. A stuck thread never blocks the
    loop or interpreter exit (it's a daemon), it only holds its slot.
    """
    if _resolver_closed:
        return _TIMED_OUT, None
    slots = _lookup_slots
    if not slots.acquire(blocking=False):
        get_logger().warning("Too many name lookups in flight; skipping %s", arg)
        return _TIMED_OUT, None
    loop = asyncio.get_running_loop()
    future: asyncio.Future[tuple[str, Any]] = loop.create_future()

    def deliver(outcome: tuple[str, Any]) -> None:
        if not future.done():
            future.set_result(outcome)

    def work() -> None:
        try:
            try:
                outcome: tuple[str, Any] = (_OK, func(arg))
            except Exception as exc:
                outcome = (_FAILED, exc)
            with contextlib.suppress(RuntimeError):  # the loop is closed
                loop.call_soon_threadsafe(deliver, outcome)
        finally:
            slots.release()

    thread = threading.Thread(target=work, name="wd-lookup", daemon=True)
    try:
        thread.start()
    except RuntimeError:  # can't start a thread (interpreter shutting down, limits)
        slots.release()
        return _TIMED_OUT, None
    try:
        async with asyncio.timeout(timeout):
            return await future
    except TimeoutError:
        return _TIMED_OUT, None


def shutdown_resolver() -> None:
    """Forget cached names and make every later lookup return ``None`` at once.

    Synchronous on purpose (``Plugin._unload`` must not await). Lookup threads
    still running are daemons and are abandoned, never joined.
    """
    global _resolver_closed
    _resolver_closed = True
    _hostname_cache.clear()
    _address_cache.clear()


def _ip_literal(value: str) -> str | None:
    """``value`` normalised if it is an IPv4 or unscoped IPv6 literal, else ``None``."""
    if "%" in value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _first_ipv4(host: str) -> str:
    """Blocking: the first IPv4 address ``host`` resolves to (raises ``OSError`` if none)."""
    infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    for _family, _type, _proto, _canon, sockaddr in infos:
        return sockaddr[0]
    raise socket.gaierror(socket.EAI_NONAME, "No IPv4 address")


async def resolve_host(
    host: str,
    timeout: float | None = None,
    resolver: Callable[[str], str] | None = None,
) -> str | None:
    """Resolve a status host to a numeric address; any failure or timeout -> ``None``.

    An IP literal is returned as-is without a lookup. A name is resolved on a
    daemon thread (``resolver`` defaults to the first IPv4 ``getaddrinfo``
    answer) and the answer is cached briefly; a timeout is not cached.
    """
    if not isinstance(host, str) or not host:
        return None
    literal = _ip_literal(host)
    if literal is not None:
        return literal
    cached = _address_cache.get(host)
    if cached is not None and cached[1] > _now():
        return cached[0]
    outcome, value = await _lookup_in_thread(
        resolver or _first_ipv4, host, STATUS_LOOKUP_TIMEOUT if timeout is None else timeout
    )
    if outcome == _TIMED_OUT:
        return None
    address = _ip_literal(value) if outcome == _OK and isinstance(value, str) else None
    if address is not None and ipaddress.ip_address(address).version != 4:
        address = None
    _address_cache[host] = (address, _now() + (ADDRESS_TTL if address else ADDRESS_MISS_TTL))
    return address


async def reverse_lookup(
    ip: str,
    timeout: float | None = None,
    resolver: Callable[[str], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """Reverse-resolve ``ip`` on a daemon thread; any failure or timeout -> ``None``.

    The name is cleaned with ``sanitise_name``. Answers (including "no name")
    are cached for a few minutes; a timeout is not cached. A timed-out thread
    may linger until the OS resolver gives up; the event loop is never blocked.
    """
    cached = _hostname_cache.get(ip)
    if cached is not None and cached[1] > clock():
        return cached[0]
    outcome, result = await _lookup_in_thread(
        resolver or socket.gethostbyaddr,
        ip,
        REVERSE_DNS_TIMEOUT if timeout is None else timeout,
    )
    if outcome == _TIMED_OUT:
        return None
    name = None
    if outcome == _OK:
        raw = result[0] if isinstance(result, tuple) and result else result
        name = sanitise_name(raw, max_len=HOST_MAX) if isinstance(raw, str) else None
    name = name or None
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
    resolver: Callable[[str], str] | None = None,
) -> str:
    """Resolve ``host`` (see ``resolve_host``), then TCP-connect to the numeric address.

    - connected, or refused (the PC's TCP stack answered) -> "awake"
    - connect timed out -> "asleep"
    - no host or port, a name that doesn't resolve in time, or no route to it
      (ENETUNREACH, ENETDOWN, EADDRNOTAVAIL, EHOSTUNREACH) -> "unknown"
    - any other connect error -> "asleep"
    """
    if not host or not port:
        return "unknown"
    address = await resolve_host(host, resolver=resolver)
    if address is None:
        return "unknown"
    open_connection = opener or asyncio.open_connection
    try:
        async with asyncio.timeout(STATUS_TIMEOUT if timeout is None else timeout):
            _reader, writer = await open_connection(address, port)
    except TimeoutError:
        return "asleep"
    except ConnectionRefusedError:
        return "awake"
    except socket.gaierror:
        return "unknown"
    except OSError as exc:
        return "unknown" if exc.errno in NO_ROUTE_ERRNOS else "asleep"
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
    resolver: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """Check every selected device concurrently; unknown ids are ignored."""
    wanted = None if ids is None else set(ids)
    selected = [d for d in devices if wanted is None or d["id"] in wanted]
    results = await asyncio.gather(
        *(
            check_status(
                d.get("host"),
                d.get("status_port"),
                timeout=timeout,
                opener=opener,
                resolver=resolver,
            )
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
