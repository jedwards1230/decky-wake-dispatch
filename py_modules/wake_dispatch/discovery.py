"""Network scan with mDNS names, and "find by IP or name".

Both only ever run because the user pressed Scan or Find in the network picker;
the automation never calls anything here, and nothing found is stored. A scan
probes the default-route interface's own private on-link /24 (or smaller), reads
the kernel's ARP table, and names what it found with reverse DNS plus mDNS
reverse-PTR queries. A find sends one probe to one typed address on that link.

Every socket, reader, clock and sleep is a parameter or a module function read at
call time, so tests never touch the real network. One scan and one find run at
a time; each is an ``asyncio.Task`` held in module state so ``cancel()`` and
``cancel_find()`` (sync, safe from ``_unload``) can stop it without awaiting.
"""

from __future__ import annotations

import asyncio
import fcntl
import ipaddress
import math
import socket
import struct
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from wake_dispatch import netinfo
from wake_dispatch.devices import HOST_MAX, sanitise_name, valid_host
from wake_dispatch.log import get_logger

# Targets
VPN_IFACE_PREFIXES = ("tun", "wg", "tailscale", "ppp", "zt")
HOME_NETWORKS = tuple(
    ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
WIDEST_PREFIX = 24
MAX_TARGETS = 254

# Probe
PROBE_PORT = 9
PROBE_INTERVAL = 0.02  # <= 50 hosts/s
ROUTE_RECHECK_EVERY = 16
MAX_IN_FLIGHT = 16  # concurrent reverse lookups (each may hold a resolver thread)
SIOCGIFADDR = 0x8915
ARP_SETTLE = 3.0  # kernel ARP retries take ~3 s to give up on a silent address

# Names
RDNS_TIMEOUT = 1.5
MDNS_ADDR = ("224.0.0.251", 5353)
MDNS_TIMEOUT = 3.0
MDNS_MAX_QUERY = 512
MDNS_MAX_DATAGRAM = 9000
MDNS_MAX_ANSWERS = 256
MDNS_MAX_ANSWERS_PER_SOURCE = 16
MDNS_MAX_HOPS = 16
MDNS_MAX_RECV_ERRORS = 16
DNS_TYPE_PTR = 12
DNS_CLASS_IN = 1
# Class IN with the unicast-response bit. Replies are unicast regardless, because the
# source port isn't 5353 (RFC 6762 legacy unicast, see mdns_lookup).
QU_CLASS = 0x8001

# Scan state
SCAN_BUDGET = 15.0
COOLDOWN = 30.0

# Find
FIND_RESOLVE_TIMEOUT = 2.0
FIND_WAIT = 2.0  # how long to watch ARP after the one probe
FIND_POLL = 0.25

NO_NETWORK = "Connect to a network to scan it"
VPN_REFUSED = "Scanning only works on a home network connection, not over a VPN"
NOT_HOME_PREFIX = "This network doesn't look like a home network, so it won't be scanned"
NO_ADDRESS = "Couldn't find this device's address on the network"
NOTHING_TO_SCAN = "There are no other addresses on this network to scan"
START_FAILED = "Couldn't start the scan"
CONFIRM_AWAY = "This doesn't look like your home network. Scan it anyway?"
BUSY = "A scan is already running"
CANCELLED = "Scan cancelled"
NETWORK_CHANGED = "The network changed during the scan"
TOO_SLOW = "The scan took too long"

FIND_BAD_INPUT = "Enter an IP address or a hostname"
FIND_UNRESOLVED = "Couldn't find that name on this network"
FIND_NO_NETWORK = "Connect to your home network to find a device"
FIND_VPN = "Finding a device only works on a home network connection, not over a VPN"
FIND_NOT_HOME = "This network doesn't look like a home network, so nothing was sent"
FIND_OFF_LINK = "That address isn't on this network"
FIND_NOT_A_HOST = "That address isn't a device on this network"
FIND_OWN = "That's this device's own address"
FIND_START_FAILED = "Couldn't send to that address"
FIND_NO_ANSWER = "No answer — is the PC on and connected to this network?"
FIND_BUSY = "Still looking — try again in a moment"
FIND_CANCELLED = "Search cancelled"

Route = dict[str, str]
RouteProbe = Callable[[], "Route | None"]
Sleep = Callable[[float], Awaitable[Any]]
Clock = Callable[[], float]
Probe = Callable[[list[str], Callable[[], None], Sleep, str], Awaitable[Any]]
Mdns = Callable[[list[str], str, dict[str, str]], Awaitable[Any]]
SendOne = Callable[[str, str], Any]


def make_socket() -> Any:
    """The one place this module opens a real socket (tests replace it)."""
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _name_or_none(value: Any) -> str | None:
    return sanitise_name(value) or None


# --------------------------------------------------------------------------- targets


def _hex_ipv4(value: str) -> str:
    return socket.inet_ntoa(struct.pack("<I", int(value, 16)))


def onlink_networks(text: str, iface: str) -> list[ipaddress.IPv4Network]:
    """Non-gateway (RTF_UP, RTF_GATEWAY clear) routes on ``iface`` from /proc/net/route text."""
    networks: list[ipaddress.IPv4Network] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8 or fields[0] != iface:
            continue
        try:
            flags = int(fields[3], 16)
            if not flags & netinfo.RTF_UP or flags & netinfo.RTF_GATEWAY:
                continue
            network = ipaddress.IPv4Network(
                f"{_hex_ipv4(fields[1])}/{_hex_ipv4(fields[7])}", strict=False
            )
        except (ValueError, struct.error, OSError):
            continue
        if network.prefixlen:
            networks.append(network)
    return networks


def local_ip(gateway: str) -> str | None:
    """This device's address towards ``gateway``: a UDP connect sends nothing."""
    try:
        sock = make_socket()
    except OSError:
        return None
    try:
        sock.connect((gateway, PROBE_PORT))
        return sock.getsockname()[0]
    except (OSError, IndexError, TypeError):
        return None
    finally:
        sock.close()


def iface_addr(iface: str) -> str | None:
    """The IPv4 address configured on ``iface`` (SIOCGIFADDR, unprivileged), or ``None``."""
    try:
        sock = make_socket()
    except OSError:
        return None
    try:
        request = struct.pack("256s", iface.encode()[:15])
        return socket.inet_ntoa(fcntl.ioctl(sock.fileno(), SIOCGIFADDR, request)[20:24])
    except (OSError, ValueError, UnicodeError, TypeError):
        return None
    finally:
        sock.close()


def _is_vpn(iface: str) -> bool:
    return iface.startswith(VPN_IFACE_PREFIXES)


def link_plan(
    *,
    route_probe: RouteProbe | None = None,
    local_ip_for: Callable[[str], str | None] | None = None,
    iface_addr_for: Callable[[str], str | None] | None = None,
    reader: netinfo.Reader | None = None,
) -> dict[str, Any]:
    """The default-route interface, this device's address on it and its on-link prefix.

    ``{ok: True, iface, gateway, own (IPv4Address), network (IPv4Network, the real
    prefix)}`` or ``{ok: False, error}`` with one of the scan's messages. Sends nothing.
    """
    route = (route_probe or netinfo.default_route)()
    if route is None:
        return {"ok": False, "error": NO_NETWORK}
    iface, gateway = route["iface"], route["gateway"]
    if _is_vpn(iface):
        return {"ok": False, "error": VPN_REFUSED}
    own_text = (local_ip_for or local_ip)(gateway)
    try:
        own = ipaddress.IPv4Address(own_text)
    except (ValueError, TypeError):
        return {"ok": False, "error": NO_ADDRESS}
    text = (reader or netinfo.read_text)(netinfo.PROC_ROUTE) or ""
    containing = [n for n in onlink_networks(text, iface) if own in n]
    if containing:
        network = max(containing, key=lambda n: n.prefixlen)
    else:
        # No on-link route to go by: only assume a /24 if the address really is this
        # interface's own (not, say, a VPN address the kernel picked for the gateway).
        if (iface_addr_for or iface_addr)(iface) != str(own):
            return {"ok": False, "error": NO_ADDRESS}
        network = ipaddress.IPv4Network(f"{own}/{WIDEST_PREFIX}", strict=False)
    if not any(network.subnet_of(home) for home in HOME_NETWORKS):
        return {"ok": False, "error": NOT_HOME_PREFIX}
    return {"ok": True, "iface": iface, "gateway": gateway, "own": own, "network": network}


def scan_targets(
    *,
    route_probe: RouteProbe | None = None,
    local_ip_for: Callable[[str], str | None] | None = None,
    iface_addr_for: Callable[[str], str | None] | None = None,
    reader: netinfo.Reader | None = None,
) -> dict[str, Any]:
    """Work out what a scan may probe, or why it may not run.

    ``{ok: True, iface, gateway, own_ip, network, targets}`` or ``{ok: False, error}``.
    """
    link = link_plan(
        route_probe=route_probe,
        local_ip_for=local_ip_for,
        iface_addr_for=iface_addr_for,
        reader=reader,
    )
    if not link["ok"]:
        return link
    iface, gateway, own, network = link["iface"], link["gateway"], link["own"], link["network"]
    if network.prefixlen < WIDEST_PREFIX:
        network = ipaddress.IPv4Network(f"{own}/{WIDEST_PREFIX}", strict=False)
    excluded = {own, network.network_address, network.broadcast_address}
    targets = [str(ip) for ip in network.hosts() if ip not in excluded][:MAX_TARGETS]
    if not targets:
        return {"ok": False, "error": NOTHING_TO_SCAN}
    return {
        "ok": True,
        "iface": iface,
        "gateway": gateway,
        "own_ip": str(own),
        "network": str(network),
        "targets": targets,
    }


# --------------------------------------------------------------------------- probe


class NetworkChanged(Exception):
    """The default route's interface or gateway changed while probing."""


def _prepare_probe_socket(sock: Any, own_ip: str) -> None:
    """Non-blocking, ``SO_DONTROUTE`` (on-link only) and bound to ``own_ip``."""
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_DONTROUTE, 1)
    sock.bind((own_ip, 0))


def send_one(ip: str, own_ip: str, socket_factory: Callable[[], Any] | None = None) -> bool:
    """Send one empty UDP datagram to ``ip`` port 9 like the scan does; True if it left.

    A socket that can't be set up raises ``OSError``; a failed send returns False.
    """
    sock = (socket_factory or make_socket)()
    try:
        _prepare_probe_socket(sock, own_ip)
        try:
            sock.sendto(b"", (ip, PROBE_PORT))
        except OSError as exc:
            get_logger().info("Find probe to %s not sent: %s", ip, exc)
            return False
        return True
    finally:
        sock.close()


async def udp_probe(
    targets: list[str],
    checkpoint: Callable[[], None],
    sleep: Sleep,
    own_ip: str,
    socket_factory: Callable[[], Any] | None = None,
) -> dict[str, int]:
    """Send one empty UDP datagram (port 9, SO_DONTROUTE) to each target, paced.

    Sending is what makes the kernel ARP for the address; whether anything listens
    on port 9 doesn't matter. Per-send errors (EHOSTUNREACH, ENOBUFS, EAGAIN, ...)
    are counted and ignored. ``checkpoint`` raises ``NetworkChanged`` to abort.
    The socket is bound to ``own_ip`` so probes can only leave by that address.
    """
    sock = (socket_factory or make_socket)()
    sent = errors = 0
    try:
        _prepare_probe_socket(sock, own_ip)
        for index, ip in enumerate(targets):
            if index:
                if index % ROUTE_RECHECK_EVERY == 0:
                    checkpoint()
                await sleep(PROBE_INTERVAL)
            try:
                sock.sendto(b"", (ip, PROBE_PORT))
                sent += 1
            except OSError:
                errors += 1
        checkpoint()
    finally:
        sock.close()
    return {"sent": sent, "errors": errors}


# --------------------------------------------------------------------------- mDNS


class Malformed(Exception):
    """An mDNS datagram that breaks a bound or doesn't parse; the whole packet is dropped."""


def reverse_name(ip: str) -> list[bytes]:
    return [part.encode() for part in reversed(ip.split("."))] + [b"in-addr", b"arpa"]


def _encode_name(labels: list[bytes]) -> bytes:
    return b"".join(bytes([len(label)]) + label for label in labels) + b"\x00"


def build_queries(ips: Iterable[str]) -> list[bytes]:
    """Reverse PTR questions for ``ips``, batched into packets of at most 512 bytes."""
    packets: list[bytes] = []
    questions: list[bytes] = []
    size = 12

    def flush() -> None:
        if questions:
            header = struct.pack("!6H", 0, 0, len(questions), 0, 0, 0)
            packets.append(header + b"".join(questions))

    for ip in ips:
        question = _encode_name(reverse_name(ip)) + struct.pack("!HH", DNS_TYPE_PTR, QU_CLASS)
        if size + len(question) > MDNS_MAX_QUERY:
            flush()
            questions, size = [], 12
        questions.append(question)
        size += len(question)
    flush()
    return packets


def read_name(data: bytes, offset: int) -> tuple[list[bytes], int]:
    """Decode a (possibly compressed) DNS name; return its labels and the offset after it.

    Pointers must point strictly backwards and at most ``MDNS_MAX_HOPS`` are
    followed; labels are <= 63 bytes and the name <= 255. Anything else raises.
    """
    labels: list[bytes] = []
    total = 1
    hops = 0
    pos = offset
    end: int | None = None
    while True:
        if pos >= len(data):
            raise Malformed("name runs past the packet")
        length = data[pos]
        kind = length & 0xC0
        if kind == 0xC0:
            if pos + 1 >= len(data):
                raise Malformed("truncated pointer")
            target = ((length & 0x3F) << 8) | data[pos + 1]
            if target >= pos:
                raise Malformed("forward or self pointer")
            hops += 1
            if hops > MDNS_MAX_HOPS:
                raise Malformed("too many pointers")
            if end is None:
                end = pos + 2
            pos = target
            continue
        if kind:
            raise Malformed("reserved label type")
        if length == 0:
            return labels, (pos + 1 if end is None else end)
        if pos + 1 + length > len(data):
            raise Malformed("label runs past the packet")
        total += length + 1
        if total > 255:
            raise Malformed("name too long")
        labels.append(data[pos + 1 : pos + 1 + length])
        pos += 1 + length


class AnswerBudget:
    """Answer records still allowed: ``MDNS_MAX_ANSWERS`` overall, a smaller cap per source."""

    def __init__(self) -> None:
        self.total = MDNS_MAX_ANSWERS
        self.per_source: dict[str, int] = {}

    def allowed(self, source: str) -> int:
        used = self.per_source.get(source, 0)
        return max(0, min(self.total, MDNS_MAX_ANSWERS_PER_SOURCE - used))

    def debit(self, source: str, count: int) -> None:
        self.total -= count
        self.per_source[source] = self.per_source.get(source, 0) + count


def _host_from(target: list[bytes]) -> str | None:
    """``host.local.`` -> ``host``; labels with a dot or that sanitise to nothing -> ``None``."""
    try:
        labels = [label.decode("utf-8") for label in target[:-1]]
    except UnicodeDecodeError as exc:
        raise Malformed("name is not UTF-8") from exc
    if any("." in label or not sanitise_name(label) for label in labels):
        return None
    return ".".join(labels)


def parse_response(data: bytes, source_ip: str, budget: AnswerBudget) -> str | None:
    """Return the ``.local`` host name a responder gave for its own address, if any.

    Only answer records actually parsed are debited from ``budget``; a packet with
    more answers than the source may still send is dropped unparsed. Raises
    ``Malformed`` on any defect.
    """
    if len(data) < 12 or len(data) > MDNS_MAX_DATAGRAM:
        raise Malformed("bad size")
    _ident, flags, qdcount, ancount, nscount, arcount = struct.unpack("!6H", data[:12])
    if not flags & 0x8000:
        raise Malformed("not a response")
    if qdcount > 64 or ancount + nscount + arcount > MDNS_MAX_ANSWERS:
        raise Malformed("implausible record counts")
    if ancount > budget.allowed(source_ip):
        raise Malformed("answer budget exhausted")
    pos = 12
    for _ in range(qdcount):
        _labels, pos = read_name(data, pos)
        pos += 4
        if pos > len(data):
            raise Malformed("truncated question")
    owner = [label.lower() for label in reverse_name(source_ip)]
    found: str | None = None
    parsed = 0
    try:
        for _ in range(ancount):
            labels, pos = read_name(data, pos)
            if pos + 10 > len(data):
                raise Malformed("truncated record")
            rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[pos : pos + 10])
            pos += 10
            rdata_end = pos + rdlength
            if rdata_end > len(data):
                raise Malformed("truncated rdata")
            parsed += 1
            if rtype == DNS_TYPE_PTR:
                target, target_end = read_name(data, pos)
                if target_end != rdata_end:
                    raise Malformed("PTR rdata length mismatch")
                if (
                    found is None
                    and rclass & 0x7FFF == DNS_CLASS_IN
                    and ttl > 0
                    and [label.lower() for label in labels] == owner
                    and len(target) >= 2
                    and target[-1].lower() == b"local"
                ):
                    found = _host_from(target)
            pos = rdata_end
    finally:
        budget.debit(source_ip, parsed)
    return _name_or_none(found)


async def mdns_lookup(
    ips: list[str],
    own_ip: str,
    found: dict[str, str],
    *,
    socket_factory: Callable[[], Any] | None = None,
    recv: Callable[[Any, int], Awaitable[tuple[bytes, Any]]] | None = None,
    clock: Clock = time.monotonic,
    timeout: float | None = None,
) -> None:
    """Ask the local network (mDNS) for the names of ``ips``; fill ``found`` as answers arrive.

    Uses one socket on an ephemeral port, never 5353. Because the query's source
    port isn't 5353, responders treat it as a legacy unicast query (RFC 6762 §6.7)
    and reply by unicast to that port. Only datagrams from port 5353 of an address
    we asked about count.
    """
    if not ips:
        return
    wanted = set(ips)
    sock = (socket_factory or make_socket)()
    try:
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(own_ip))
        sock.bind(("", 0))
        receive = recv or asyncio.get_running_loop().sock_recvfrom
        deadline = clock() + (MDNS_TIMEOUT if timeout is None else timeout)
        for packet in build_queries(ips):
            try:
                sock.sendto(packet, MDNS_ADDR)
            except OSError as exc:
                get_logger().info("mDNS query not sent: %s", exc)
        budget = AnswerBudget()
        errors = 0
        while budget.total > 0 and len(found) < len(wanted):
            remaining = deadline - clock()
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    data, address = await receive(sock, MDNS_MAX_DATAGRAM + 1)
            except TimeoutError:
                break
            except OSError:
                errors += 1
                if errors >= MDNS_MAX_RECV_ERRORS:
                    break
                continue
            if not isinstance(address, tuple) or len(address) < 2:
                continue
            source, port = address[0], address[1]
            if port != MDNS_ADDR[1] or source not in wanted or source in found:
                continue
            try:
                name = parse_response(data, source, budget)
            except (Malformed, struct.error):
                continue
            if name:
                found[source] = name
    finally:
        sock.close()


# --------------------------------------------------------------------------- scan


class _ScanState:
    def __init__(self) -> None:
        self.task: asyncio.Task[dict[str, Any]] | None = None
        self.completed_at: float | None = None
        self.find_task: asyncio.Task[dict[str, Any]] | None = None


_state = _ScanState()


def cancel() -> bool:
    """Cancel a running scan without awaiting it; True if one was running."""
    task = _state.task
    if task is None or task.done() or task.cancelling():
        return False
    task.cancel()
    return True


def cancel_find() -> bool:
    """Cancel a pending find without awaiting it; True if one was running."""
    task = _state.find_task
    if task is None or task.done() or task.cancelling():
        return False
    task.cancel()
    return True


async def _await_task(task: asyncio.Task[dict[str, Any]], cancelled: dict[str, Any]) -> Any:
    """Await ``task``; if only the task (not the caller) was cancelled, return ``cancelled``."""
    try:
        return await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if task.cancelled() and (current is None or not current.cancelling()):
            return cancelled
        raise


def _home_gateways(devices: Iterable[dict[str, Any]]) -> set[str]:
    return {d["home_gateway"] for d in devices if isinstance(d, dict) and d.get("home_gateway")}


async def scan_network(
    confirm_away: bool,
    *,
    devices: list[dict[str, Any]],
    route_probe: RouteProbe | None = None,
    local_ip_for: Callable[[str], str | None] | None = None,
    iface_addr_for: Callable[[str], str | None] | None = None,
    reader: netinfo.Reader | None = None,
    probe: Probe | None = None,
    mdns: Mdns | None = None,
    resolver: Callable[[str], Any] | None = None,
    sleep: Sleep | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Run one user-initiated scan (see docs/CONTRACT.md §4 for the bounds)."""
    now_clock = clock or time.monotonic
    if _state.task is not None and not _state.task.done():
        return {"ok": False, "error": BUSY, "busy": True}
    if _state.completed_at is not None:
        wait = COOLDOWN - (now_clock() - _state.completed_at)
        if wait > 0:
            retry_in = max(1, math.ceil(wait))
            return {
                "ok": False,
                "error": f"Scanned a moment ago — try again in {retry_in} s",
                "retry_in": retry_in,
            }
    route_check = route_probe or netinfo.default_route
    plan = scan_targets(
        route_probe=route_check,
        local_ip_for=local_ip_for,
        iface_addr_for=iface_addr_for,
        reader=reader,
    )
    if not plan["ok"]:
        return plan
    if confirm_away is not True and plan["gateway"] not in _home_gateways(devices):
        return {
            "ok": False,
            "needs_confirm": True,
            "gateway": plan["gateway"],
            "error": CONFIRM_AWAY,
        }
    task = asyncio.ensure_future(
        _run_scan(
            plan,
            route_check=route_check,
            reader=reader,
            probe=probe or udp_probe,
            mdns=mdns or mdns_lookup,
            resolver=resolver,
            sleep=sleep or asyncio.sleep,
            clock=now_clock,
        )
    )
    _state.task = task
    try:
        result = await _await_task(task, {"ok": False, "error": CANCELLED, "cancelled": True})
        if result.get("cancelled"):
            get_logger().info("Network scan cancelled")
        return result
    finally:
        if _state.task is task:
            _state.task = None


async def _run_scan(
    plan: dict[str, Any],
    *,
    route_check: RouteProbe,
    reader: netinfo.Reader | None,
    probe: Probe,
    mdns: Mdns,
    resolver: Callable[[str], Any] | None,
    sleep: Sleep,
    clock: Clock,
) -> dict[str, Any]:
    started = clock()
    iface, gateway, targets = plan["iface"], plan["gateway"], plan["targets"]
    expected = {"iface": iface, "gateway": gateway}

    def checkpoint() -> None:
        current = route_check()
        if current is None or {k: current.get(k) for k in expected} != expected:
            raise NetworkChanged

    found: list[dict[str, Any]] | None = None
    mdns_names: dict[str, str] = {}
    dns_names: dict[str, str] = {}
    allowed = set(targets) | {gateway}
    in_flight = asyncio.Semaphore(MAX_IN_FLIGHT)

    async def rdns(ip: str) -> None:
        try:
            async with in_flight:
                name = await netinfo.reverse_lookup(ip, timeout=RDNS_TIMEOUT, resolver=resolver)
        except Exception as exc:  # a broken lookup must not fail the scan
            get_logger().info("Reverse lookup for %s failed: %r", ip, exc)
            return
        name = _name_or_none(name)
        if name:
            dns_names[ip] = name

    async def mdns_safe(ips: list[str]) -> None:
        try:
            await mdns(ips, plan["own_ip"], mdns_names)
        except Exception as exc:
            get_logger().info("mDNS lookups failed: %r", exc)

    try:
        async with asyncio.timeout(SCAN_BUDGET):
            try:
                await probe(targets, checkpoint, sleep, plan["own_ip"])
            except OSError as exc:
                get_logger().error("Network scan could not start: %s", exc)
                return {"ok": False, "error": START_FAILED}
            await sleep(ARP_SETTLE)
            checkpoint()
            text = (reader or netinfo.read_text)(netinfo.PROC_ARP) or ""
            found = [
                e for e in netinfo.parse_arp(text) if e["iface"] == iface and e["ip"] in allowed
            ]
            ips = [e["ip"] for e in found]
            await asyncio.gather(*(rdns(ip) for ip in ips), mdns_safe(ips))
    except NetworkChanged:
        _state.completed_at = clock()
        get_logger().warning("Network scan aborted: the default route changed")
        return {"ok": False, "error": NETWORK_CHANGED}
    except TimeoutError:
        _state.completed_at = clock()
        if found is None:
            get_logger().warning("Network scan ran out of time before reading ARP")
            return {"ok": False, "error": TOO_SLOW}
        get_logger().warning("Network scan ran out of time while naming devices")
    _state.completed_at = clock()
    try:
        checkpoint()  # don't report devices from a network we've since left
    except NetworkChanged:
        get_logger().warning("Network scan aborted: the default route changed")
        return {"ok": False, "error": NETWORK_CHANGED}

    present = []
    for entry in found:
        ip = entry["ip"]
        if ip in mdns_names:
            name, source = mdns_names[ip], "mdns"
        elif ip in dns_names:
            name, source = dns_names[ip], "dns"
        else:
            name, source = None, None
        present.append(
            {
                "ip": ip,
                "mac": entry["mac"],
                "iface": entry["iface"],
                "hostname": name,
                "name_source": source,
            }
        )

    result = {
        "ok": True,
        "neighbours": present,
        "probed": len(targets),
        "found": len(present),
        "named": sum(1 for e in present if e["name_source"]),
        "duration_ms": max(0, int((clock() - started) * 1000)),
        "gateway": gateway,
    }
    get_logger().info(
        "Network scan of %s: %d probed, %d found, %d named in %d ms",
        plan["network"],
        result["probed"],
        result["found"],
        result["named"],
        result["duration_ms"],
    )
    return result


# --------------------------------------------------------------------------- find


def _arp_entry(text: str, iface: str, ip: str) -> dict[str, str] | None:
    for entry in netinfo.parse_arp(text):
        if entry["iface"] == iface and entry["ip"] == ip:
            return entry
    return None


async def find_host(
    address: Any,
    *,
    route_probe: RouteProbe | None = None,
    local_ip_for: Callable[[str], str | None] | None = None,
    iface_addr_for: Callable[[str], str | None] | None = None,
    reader: netinfo.Reader | None = None,
    resolve: Callable[..., Awaitable[str | None]] | None = None,
    send: SendOne | None = None,
    resolver: Callable[[str], Any] | None = None,
    sleep: Sleep | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Find one device the user typed (IPv4 address or hostname) on this link.

    ``{ok: True, ip, mac, name, name_source: "typed" | "dns" | None}`` or
    ``{ok: False, error}``. At most one probe to one on-link address; nothing is
    stored. Not subject to the scan's lock or cooldown; one find at a time.
    """
    if _state.find_task is not None and not _state.find_task.done():
        return {"ok": False, "error": FIND_BUSY, "busy": True}
    task = asyncio.ensure_future(
        _run_find(
            address,
            route_probe=route_probe,
            local_ip_for=local_ip_for,
            iface_addr_for=iface_addr_for,
            reader=reader,
            resolve=resolve or netinfo.resolve_host,
            send=send or send_one,
            resolver=resolver,
            sleep=sleep or asyncio.sleep,
            clock=clock or time.monotonic,
        )
    )
    _state.find_task = task
    try:
        return await _await_task(task, {"ok": False, "error": FIND_CANCELLED, "cancelled": True})
    finally:
        if _state.find_task is task:
            _state.find_task = None


def _typed_address(address: Any) -> tuple[str, bool] | None:
    """``(address, is_ip)`` for an IPv4 literal or RFC 1123 hostname, else ``None``."""
    if not isinstance(address, str):
        return None
    text = address.strip()
    if not text or len(text.rstrip(".")) > HOST_MAX or not valid_host(text):
        return None
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return text, False
    return (str(ip), True) if ip.version == 4 else None


_FIND_LINK_ERRORS = {
    NO_NETWORK: FIND_NO_NETWORK,
    VPN_REFUSED: FIND_VPN,
    NOT_HOME_PREFIX: FIND_NOT_HOME,
}


async def _run_find(
    address: Any,
    *,
    route_probe: RouteProbe | None,
    local_ip_for: Callable[[str], str | None] | None,
    iface_addr_for: Callable[[str], str | None] | None,
    reader: netinfo.Reader | None,
    resolve: Callable[..., Awaitable[str | None]],
    send: SendOne,
    resolver: Callable[[str], Any] | None,
    sleep: Sleep,
    clock: Clock,
) -> dict[str, Any]:
    typed = _typed_address(address)
    if typed is None:
        return {"ok": False, "error": FIND_BAD_INPUT}
    text, is_ip = typed
    link = link_plan(
        route_probe=route_probe,
        local_ip_for=local_ip_for,
        iface_addr_for=iface_addr_for,
        reader=reader,
    )
    if not link["ok"]:
        return {"ok": False, "error": _FIND_LINK_ERRORS.get(link["error"], link["error"])}
    resolved = text if is_ip else await resolve(text, timeout=FIND_RESOLVE_TIMEOUT)
    current = (route_probe or netinfo.default_route)()  # the lookup may have taken a while
    if current is None or (current.get("iface"), current.get("gateway")) != (
        link["iface"],
        link["gateway"],
    ):
        moved_to_vpn = current is not None and _is_vpn(str(current.get("iface", "")))
        return {"ok": False, "error": FIND_VPN if moved_to_vpn else FIND_NO_NETWORK}
    try:
        ip = ipaddress.IPv4Address(resolved)
    except (ValueError, TypeError):
        return {"ok": False, "error": FIND_UNRESOLVED}
    network, iface, own = link["network"], link["iface"], link["own"]
    if ip == own:
        return {"ok": False, "error": FIND_OWN}
    if ip not in network:
        return {"ok": False, "error": FIND_OFF_LINK}
    if network.prefixlen < 31 and ip in (network.network_address, network.broadcast_address):
        return {"ok": False, "error": FIND_NOT_A_HOST}
    read = reader or netinfo.read_text
    target = str(ip)
    entry = _arp_entry(read(netinfo.PROC_ARP) or "", iface, target)
    if entry is None:
        try:
            sent = send(target, str(own))
        except OSError as exc:
            get_logger().error("Find could not send to %s: %s", target, exc)
            return {"ok": False, "error": FIND_START_FAILED}
        if not sent:
            return {"ok": False, "error": FIND_START_FAILED}
        deadline = clock() + FIND_WAIT
        while entry is None:
            if clock() >= deadline:
                return {"ok": False, "error": FIND_NO_ANSWER}
            await sleep(FIND_POLL)
            entry = _arp_entry(read(netinfo.PROC_ARP) or "", iface, target)
    if is_ip:
        name = await netinfo.reverse_lookup(target, timeout=RDNS_TIMEOUT, resolver=resolver)
        name, source = _name_or_none(name), "dns"
    else:
        name, source = _name_or_none(text.rstrip(".")), "typed"
    return {
        "ok": True,
        "ip": target,
        "mac": entry["mac"],
        "name": name,
        "name_source": source if name else None,
    }
