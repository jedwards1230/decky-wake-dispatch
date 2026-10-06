"""Network scan, mDNS parsing and find-by-address. No real sockets or DNS."""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import socket
import struct
from pathlib import Path
from typing import Any

import pytest
from helpers import HOME_ROUTE, ROUTE_HEADER, device, write_network

import main
from wake_dispatch import discovery, netinfo

GW = "192.168.1.1"
OWN = "192.168.1.50"
ROUTE = {"iface": "wlan0", "gateway": GW}
ARP_HEADER = "IP address       HW type     Flags       HW address            Mask     Device\n"


def le(ip: Any) -> str:
    return format(struct.unpack("<I", socket.inet_aton(str(ip)))[0], "08X")


def onlink(iface: str, cidr: str, flags: str = "0001") -> str:
    net = ipaddress.IPv4Network(cidr)
    return (
        f"{iface}\t{le(net.network_address)}\t00000000\t{flags}\t0\t0\t0\t"
        f"{le(net.netmask)}\t0\t0\t0\n"
    )


def default_line(iface: str = "wlan0", gateway: str = GW) -> str:
    return f"{iface}\t00000000\t{le(gateway)}\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"


def routes(*lines: str) -> str:
    return ROUTE_HEADER + "".join(lines)


def arp(*entries: tuple[str, str, str]) -> str:
    return ARP_HEADER + "".join(f"{ip} 0x1 0x2 {mac} * {iface}\n" for ip, mac, iface in entries)


def mac(n: int) -> str:
    return f"aa:bb:cc:dd:ee:{n:02x}"


def targets_for(
    cidr_lines: str,
    *,
    iface: str = "wlan0",
    own: str | None = OWN,
    gw: str = GW,
    configured: str | None | object = ...,
):
    files = {netinfo.PROC_ROUTE: cidr_lines}
    on_iface = own if configured is ... else configured
    return discovery.scan_targets(
        route_probe=lambda: {"iface": iface, "gateway": gw},
        local_ip_for=lambda _gw: own,
        iface_addr_for=lambda _iface: on_iface,
        reader=files.get,
    )


# --------------------------------------------------------------------------- targets


def test_targets_slash_24_excludes_own_network_and_broadcast() -> None:
    plan = targets_for(routes(default_line(), onlink("wlan0", "192.168.1.0/24")))
    assert plan["ok"] and plan["network"] == "192.168.1.0/24"
    assert len(plan["targets"]) == 253
    assert OWN not in plan["targets"]
    assert "192.168.1.0" not in plan["targets"] and "192.168.1.255" not in plan["targets"]
    assert plan["targets"][0] == GW and plan["targets"][-1] == "192.168.1.254"
    assert (plan["iface"], plan["gateway"], plan["own_ip"]) == ("wlan0", GW, OWN)


@pytest.mark.parametrize("cidr", ["192.168.0.0/23", "192.168.0.0/16", "10.0.0.0/8"])
def test_wider_prefix_scans_only_own_slash_24(cidr: str) -> None:
    own = OWN if not cidr.startswith("10.") else "10.1.2.3"
    plan = targets_for(routes(onlink("wlan0", cidr)), own=own)
    expected = str(ipaddress.IPv4Network(f"{own}/24", strict=False))
    assert plan["ok"] and plan["network"] == expected
    assert len(plan["targets"]) == 253


def test_slash_25_is_scanned_as_is() -> None:
    plan = targets_for(routes(onlink("wlan0", "192.168.1.0/25")))
    assert plan["network"] == "192.168.1.0/25"
    assert len(plan["targets"]) == 125  # .1-.126 minus own
    assert "192.168.1.127" not in plan["targets"]


def test_most_specific_onlink_route_wins_and_other_ifaces_ignored() -> None:
    text = routes(
        onlink("wlan0", "192.168.0.0/16"),
        onlink("wlan0", "192.168.1.0/26"),
        onlink("eth0", "192.168.1.0/28"),
        onlink("wlan0", "192.168.1.0/27", flags="0003"),  # gateway route, not on-link
        onlink("wlan0", "192.168.1.0/29", flags="0000"),  # not up
    )
    assert targets_for(text)["network"] == "192.168.1.0/26"


def test_no_onlink_route_assumes_slash_24() -> None:
    plan = targets_for(routes(default_line()))
    assert plan["ok"] and plan["network"] == "192.168.1.0/24"


@pytest.mark.parametrize("configured", [None, "10.8.0.2"])
def test_no_onlink_route_needs_own_ip_on_the_interface(configured) -> None:
    plan = targets_for(routes(default_line()), configured=configured)
    assert plan == {"ok": False, "error": discovery.NO_ADDRESS}


def test_onlink_route_skips_interface_address_check() -> None:
    plan = targets_for(routes(onlink("wlan0", "192.168.1.0/24")), configured=None)
    assert plan["ok"]


def test_iface_addr_uses_siocgifaddr(monkeypatch) -> None:
    calls = []

    class IoctlSocket(FakeUdp):
        def fileno(self) -> int:
            return 99

    fake = IoctlSocket()

    def ioctl(fd, request, arg):
        calls.append((fd, request, arg[:16]))
        return arg[:20] + socket.inet_aton(OWN) + arg[24:]

    monkeypatch.setattr(discovery, "make_socket", lambda: fake)
    monkeypatch.setattr(discovery.fcntl, "ioctl", ioctl)
    assert discovery.iface_addr("wlan0") == OWN
    assert calls == [(99, 0x8915, b"wlan0" + b"\x00" * 11)] and fake.closed

    def failing(*_a):
        raise OSError(errno.EADDRNOTAVAIL, "no address")

    monkeypatch.setattr(discovery.fcntl, "ioctl", failing)
    assert discovery.iface_addr("wlan0") is None


@pytest.mark.parametrize(
    ("own", "cidr"),
    [
        ("198.51.100.7", "198.51.100.0/24"),  # public
        ("100.64.1.5", "100.64.0.0/10"),  # CGNAT
        ("169.254.3.4", "169.254.0.0/16"),  # link-local
        ("127.0.0.5", "127.0.0.0/8"),  # loopback
        ("192.168.1.50", "192.0.0.0/8"),  # on-link route wider than the private block
    ],
)
def test_non_home_prefixes_are_refused(own: str, cidr: str) -> None:
    plan = targets_for(routes(onlink("wlan0", cidr)), own=own)
    assert plan == {"ok": False, "error": discovery.NOT_HOME_PREFIX}


@pytest.mark.parametrize("iface", ["tun0", "wg0", "tailscale0", "ppp0", "zt1234"])
def test_vpn_interfaces_are_refused(iface: str) -> None:
    plan = targets_for(routes(onlink(iface, "10.0.0.0/24")), iface=iface, own="10.0.0.2")
    assert plan == {"ok": False, "error": discovery.VPN_REFUSED}


def test_target_cap(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "MAX_TARGETS", 10)
    assert len(targets_for(routes(onlink("wlan0", "192.168.1.0/24")))["targets"]) == 10


def test_no_route_no_address_and_nothing_to_scan() -> None:
    assert discovery.scan_targets(route_probe=lambda: None)["error"] == discovery.NO_NETWORK
    assert targets_for(routes(), own=None)["error"] == discovery.NO_ADDRESS
    assert targets_for(routes(), own="not an ip")["error"] == discovery.NO_ADDRESS
    plan = targets_for(routes(onlink("wlan0", "192.168.1.50/32")))
    assert plan == {"ok": False, "error": discovery.NOTHING_TO_SCAN}


class FakeUdp:
    def __init__(self, fail: dict[str, OSError] | None = None, name: Any = (OWN, 40000)) -> None:
        self.fail = fail or {}
        self.name = name
        self.options: list[tuple[int, int, Any]] = []
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.connected: tuple[str, int] | None = None
        self.bound: tuple[str, int] | None = None
        self.blocking: bool | None = None
        self.closed = False

    def setblocking(self, flag: bool) -> None:
        self.blocking = flag

    def setsockopt(self, level: int, option: int, value: Any) -> None:
        self.options.append((level, option, value))

    def connect(self, address: tuple[str, int]) -> None:
        self.connected = address

    def getsockname(self) -> Any:
        return self.name

    def bind(self, address: tuple[str, int]) -> None:
        self.bound = address

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        if address[0] in self.fail:
            raise self.fail[address[0]]
        self.sent.append((data, address))
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_local_ip_connects_without_sending(monkeypatch) -> None:
    fake = FakeUdp()
    monkeypatch.setattr(discovery, "make_socket", lambda: fake)
    assert discovery.local_ip(GW) == OWN
    assert fake.connected == (GW, 9) and fake.sent == [] and fake.closed


def test_local_ip_failure_is_none(monkeypatch) -> None:
    class Unreachable(FakeUdp):
        def connect(self, address: tuple[str, int]) -> None:
            raise OSError(errno.ENETUNREACH, "unreachable")

    fake = Unreachable()
    monkeypatch.setattr(discovery, "make_socket", lambda: fake)
    assert discovery.local_ip(GW) is None and fake.closed


def test_sandbox_forbids_real_sockets() -> None:
    with pytest.raises(AssertionError, match="real socket"):
        discovery.make_socket()


# --------------------------------------------------------------------------- probe


async def test_probe_paces_counts_and_rechecks_route() -> None:
    targets = [f"192.168.1.{i}" for i in range(1, 41)]
    fake = FakeUdp(fail={"192.168.1.5": OSError(errno.EHOSTUNREACH, "x")})
    sleeps: list[float] = []
    checks: list[int] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)

    result = await discovery.udp_probe(
        targets, lambda: checks.append(len(fake.sent)), sleep, OWN, socket_factory=lambda: fake
    )
    assert result == {"sent": 39, "errors": 1}
    assert [a for _d, a in fake.sent][:2] == [("192.168.1.1", 9), ("192.168.1.2", 9)]
    assert all(d == b"" for d, _a in fake.sent)
    assert sleeps == [0.02] * 39  # 50 hosts/s
    assert len(checks) == 3  # before send 16 and 32, and after the last
    assert (socket.SOL_SOCKET, socket.SO_DONTROUTE, 1) in fake.options
    assert fake.blocking is False and fake.closed
    assert fake.bound == (OWN, 0)


async def test_probe_socket_errors_escape_to_the_scan() -> None:
    class NoDontRoute(FakeUdp):
        def setsockopt(self, level: int, option: int, value: Any) -> None:
            raise OSError(errno.EPERM, "not permitted")

    fake = NoDontRoute()

    async def sleep(_s: float) -> None:
        return None

    with pytest.raises(OSError):
        await discovery.udp_probe(["192.168.1.2"], lambda: None, sleep, OWN, lambda: fake)
    assert fake.closed


@pytest.mark.parametrize("code", [errno.EHOSTUNREACH, errno.ENOBUFS, errno.EAGAIN])
async def test_probe_tolerates_send_errors(code: int) -> None:
    fake = FakeUdp(fail={"192.168.1.2": OSError(code, "x")})

    async def sleep(_s: float) -> None:
        return None

    result = await discovery.udp_probe(
        ["192.168.1.2", "192.168.1.3"], lambda: None, sleep, OWN, socket_factory=lambda: fake
    )
    assert result == {"sent": 1, "errors": 1}


async def test_probe_abort_closes_socket() -> None:
    fake = FakeUdp()

    def checkpoint() -> None:
        raise discovery.NetworkChanged

    async def sleep(_s: float) -> None:
        return None

    targets = [f"192.168.1.{i}" for i in range(1, 30)]
    with pytest.raises(discovery.NetworkChanged):
        await discovery.udp_probe(targets, checkpoint, sleep, OWN, socket_factory=lambda: fake)
    assert len(fake.sent) == 16 and fake.closed


# --------------------------------------------------------------------------- mDNS


def dns_name(*labels: bytes) -> bytes:
    return b"".join(bytes([len(x)]) + x for x in labels) + b"\x00"


def mdns_response(
    source: str,
    host: bytes = b"gamingpc",
    *,
    owner: bytes | None = None,
    target: bytes | None = None,
    ttl: int = 120,
    rclass: int = 0x8001,
    ancount: int | None = None,
    flags: int = 0x8400,
) -> bytes:
    owner = dns_name(*discovery.reverse_name(source)) if owner is None else owner
    target = dns_name(host, b"local") if target is None else target
    record = owner + struct.pack("!HHIH", 12, rclass, ttl, len(target)) + target
    header = struct.pack("!6H", 0, flags, 0, 1 if ancount is None else ancount, 0, 0)
    return header + record


def parse(data: bytes, source: str = "192.168.1.20", budget: int = 256) -> str | None:
    answers = discovery.AnswerBudget()
    answers.total = budget
    return discovery.parse_response(data, source, answers)


def test_parse_valid_answer() -> None:
    assert parse(mdns_response("192.168.1.20")) == "gamingpc"


def test_parse_compression_pointer_to_question() -> None:
    question = dns_name(*discovery.reverse_name("192.168.1.20")) + struct.pack("!HH", 12, 1)
    target = dns_name(b"media", b"local")
    answer = b"\xc0\x0c" + struct.pack("!HHIH", 12, 1, 120, len(target)) + target
    data = struct.pack("!6H", 0, 0x8400, 1, 1, 0, 0) + question + answer
    assert parse(data) == "media"


def test_parse_pointer_loop_and_forward_pointer_are_malformed() -> None:
    header = struct.pack("!6H", 0, 0x8400, 0, 1, 0, 0)
    with pytest.raises(discovery.Malformed):
        parse(header + b"\xc0\x0c" + b"\x00" * 10)  # points at itself
    with pytest.raises(discovery.Malformed):
        parse(header + b"\xc0\x20" + b"\x00" * 40)  # points forwards


def test_read_name_hop_limit() -> None:
    data = bytearray(b"\x00" * 12 + b"\x00")  # terminator at 12
    previous = 12
    for _ in range(discovery.MDNS_MAX_HOPS + 1):
        here = len(data)
        data += bytes([0xC0 | (previous >> 8), previous & 0xFF])
        previous = here
    with pytest.raises(discovery.Malformed, match="too many"):
        discovery.read_name(bytes(data), previous)
    assert discovery.read_name(bytes(data), 13) == ([], 15)


def test_parse_rejects_bad_labels() -> None:
    header = struct.pack("!6H", 0, 0x8400, 0, 1, 0, 0)
    with pytest.raises(discovery.Malformed):
        parse(header + b"\x40" + b"a" * 64 + b"\x00")  # reserved label type / > 63
    long_name = b"".join(b"\x3f" + b"a" * 63 for _ in range(5)) + b"\x00"
    with pytest.raises(discovery.Malformed, match="too long"):
        parse(header + long_name + b"\x00" * 10)


@pytest.mark.parametrize("cut", [1, 5, 12, 20])
def test_parse_truncated_packet(cut: int) -> None:
    data = mdns_response("192.168.1.20")
    with pytest.raises(discovery.Malformed):
        parse(data[:-cut])


def test_parse_too_many_answers_and_budget() -> None:
    with pytest.raises(discovery.Malformed):
        parse(mdns_response("192.168.1.20", ancount=300))
    with pytest.raises(discovery.Malformed, match="budget"):
        parse(mdns_response("192.168.1.20"), budget=0)
    budget = discovery.AnswerBudget()
    discovery.parse_response(mdns_response("192.168.1.20"), "192.168.1.20", budget)
    assert budget.total == 255 and budget.per_source == {"192.168.1.20": 1}


def test_budget_debits_only_parsed_records() -> None:
    budget = discovery.AnswerBudget()
    bogus = mdns_response("192.168.1.20", ancount=200)  # claims 200, holds 1
    with pytest.raises(discovery.Malformed):
        discovery.parse_response(bogus, "192.168.1.20", budget)
    assert budget.total == 256  # over the per-source cap: dropped unparsed
    truncated = mdns_response("192.168.1.20", ancount=3)
    with pytest.raises(discovery.Malformed):
        discovery.parse_response(truncated, "192.168.1.20", budget)
    assert budget.total == 255 and budget.per_source == {"192.168.1.20": 1}


def test_budget_caps_each_source() -> None:
    budget = discovery.AnswerBudget()
    for _ in range(discovery.MDNS_MAX_ANSWERS_PER_SOURCE):
        discovery.parse_response(mdns_response("192.168.1.20"), "192.168.1.20", budget)
    with pytest.raises(discovery.Malformed, match="budget"):
        discovery.parse_response(mdns_response("192.168.1.20"), "192.168.1.20", budget)
    assert discovery.parse_response(mdns_response("192.168.1.21"), "192.168.1.21", budget)


@pytest.mark.parametrize("label", [b"a.b", b"\xe2\x80\x8b", b" "])
def test_labels_with_dots_or_nothing_left_are_rejected(label: bytes) -> None:
    assert parse(mdns_response("192.168.1.20", label)) is None


def test_parse_oversize_and_query_rejected() -> None:
    with pytest.raises(discovery.Malformed):
        parse(mdns_response("192.168.1.20") + b"\x00" * 9000)
    with pytest.raises(discovery.Malformed, match="not a response"):
        parse(mdns_response("192.168.1.20", flags=0))


def test_parse_ignores_answers_for_other_addresses_and_non_local_names() -> None:
    assert parse(mdns_response("192.168.1.21"), source="192.168.1.20") is None
    assert parse(mdns_response("192.168.1.20", target=dns_name(b"pc", b"example"))) is None
    assert parse(mdns_response("192.168.1.20", ttl=0)) is None  # goodbye packet
    assert parse(mdns_response("192.168.1.20", rclass=3)) is None


def test_parse_case_insensitive_owner() -> None:
    owner = dns_name(b"20", b"1", b"168", b"192", b"IN-ADDR", b"ARPA")
    assert parse(mdns_response("192.168.1.20", owner=owner)) == "gamingpc"


def test_parse_sanitises_bidi_and_zero_width() -> None:
    host = "game‮pc​".encode()
    assert parse(mdns_response("192.168.1.20", host)) == "gamepc"
    with pytest.raises(discovery.Malformed):
        parse(mdns_response("192.168.1.20", b"\xff\xfe"))


def test_build_queries_batches_under_512_bytes() -> None:
    ips = [f"192.168.1.{i}" for i in range(1, 255)]
    packets = discovery.build_queries(ips)
    assert len(packets) > 1 and all(len(p) <= 512 for p in packets)
    total = 0
    for packet in packets:
        _id, flags, qd, an, ns, ar = struct.unpack("!6H", packet[:12])
        assert (flags, an, ns, ar) == (0, 0, 0, 0)
        pos = 12
        for _ in range(qd):
            labels, pos = discovery.read_name(packet, pos)
            assert labels[-2:] == [b"in-addr", b"arpa"]
            assert struct.unpack("!HH", packet[pos : pos + 4]) == (12, 0x8001)
            pos += 4
        assert pos == len(packet)
        total += qd
    assert total == 254
    assert discovery.build_queries([]) == []


def scripted_recv(datagrams: list[tuple[bytes, Any]], clock: list[float], step: float = 0.0):
    queue = list(datagrams)
    calls: list[int] = []

    async def recv(_sock: Any, size: int) -> tuple[bytes, Any]:
        calls.append(size)
        clock[0] += step
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        clock[0] += 1000  # past any deadline
        return b"", ("192.0.2.99", 5353)

    recv.calls = calls  # type: ignore[attr-defined]
    return recv


async def test_mdns_lookup_socket_setup_and_filters() -> None:
    fake = FakeUdp()
    clock = [0.0]
    a, b = "192.168.1.20", "192.168.1.30"
    recv = scripted_recv(
        [
            (mdns_response("192.168.1.99", b"spoof"), ("192.168.1.99", 5353)),  # not asked
            (mdns_response(a, b"wrongport"), (a, 5354)),
            (b"\x00garbage", (a, 5353)),
            (mdns_response(a), (a, 5353)),
            (mdns_response(a, b"again"), (a, 5353)),  # first answer wins
            (mdns_response(b, b"nas"), (b, 5353)),
        ],
        clock,
    )
    found: dict[str, str] = {}
    await discovery.mdns_lookup(
        [a, b], OWN, found, socket_factory=lambda: fake, recv=recv, clock=lambda: clock[0]
    )
    assert found == {a: "gamingpc", b: "nas"}
    assert fake.bound == ("", 0)  # ephemeral, never 5353
    assert fake.blocking is False and fake.closed
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255) in fake.options
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0) in fake.options
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(OWN)) in fake.options
    assert {addr for _d, addr in fake.sent} == {("224.0.0.251", 5353)}
    assert recv.calls[0] == 9001  # type: ignore[attr-defined]


async def test_mdns_deadline_with_injected_clock() -> None:
    fake = FakeUdp()
    clock = [0.0]
    junk = [(b"junk", ("192.168.1.20", 5353))] * 50
    recv = scripted_recv(junk, clock, step=1.0)
    found: dict[str, str] = {}
    await discovery.mdns_lookup(
        ["192.168.1.20"], OWN, found, socket_factory=lambda: fake, recv=recv, clock=lambda: clock[0]
    )
    assert len(recv.calls) == 3  # type: ignore[attr-defined]
    assert found == {} and fake.closed


async def test_mdns_real_timeout_and_errors() -> None:
    fake = FakeUdp()

    async def hang(_sock: Any, _size: int) -> Any:
        await asyncio.Event().wait()

    await discovery.mdns_lookup(
        ["192.168.1.20"], OWN, {}, socket_factory=lambda: fake, recv=hang, timeout=0.01
    )
    assert fake.closed
    errors = []

    async def failing(_sock: Any, _size: int) -> Any:
        errors.append(1)
        raise OSError(errno.ECONNREFUSED, "refused")

    await discovery.mdns_lookup(
        ["192.168.1.20"], OWN, {}, socket_factory=lambda: FakeUdp(), recv=failing, clock=lambda: 0
    )
    assert len(errors) == discovery.MDNS_MAX_RECV_ERRORS


async def test_mdns_send_failure_is_tolerated() -> None:
    fake = FakeUdp(fail={"224.0.0.251": OSError(errno.ENETUNREACH, "x")})
    clock = [0.0]
    await discovery.mdns_lookup(
        ["192.168.1.20"],
        OWN,
        {},
        socket_factory=lambda: fake,
        recv=scripted_recv([], clock),
        clock=lambda: clock[0],
    )
    assert fake.closed


async def test_mdns_answer_budget_stops_receiving(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "MDNS_MAX_ANSWERS", 2)
    clock = [0.0]
    ips = [f"192.168.1.{i}" for i in (20, 21, 22)]
    recv = scripted_recv(
        [(mdns_response(ip, b"h" + ip[-2:].encode()), (ip, 5353)) for ip in ips], clock
    )
    found: dict[str, str] = {}
    await discovery.mdns_lookup(
        ips, OWN, found, socket_factory=lambda: FakeUdp(), recv=recv, clock=lambda: clock[0]
    )
    assert len(found) == 2 and len(recv.calls) == 2  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- scan harness


class Harness:
    def __init__(self, runtime: str, arp_entries=(), *, mdns=None, dns=None) -> None:
        self.runtime = runtime
        self.files = {
            netinfo.PROC_ROUTE: routes(default_line(), onlink("wlan0", "192.168.1.0/24")),
            netinfo.PROC_ARP: arp(*arp_entries),
        }
        self.route: dict[str, str] | None = dict(ROUTE)
        self.mdns_names = mdns or {}
        self.dns = dns or {}
        self.clock = [100.0]
        self.sleeps: list[float] = []
        self.probed: list[list[str]] = []
        self.gate: asyncio.Event | None = None
        self.on_probe = None

    async def probe(self, targets, checkpoint, sleep, own_ip) -> None:
        assert own_ip == OWN
        self.probed.append(list(targets))
        if self.on_probe:
            self.on_probe()
        if self.gate is not None:
            await self.gate.wait()
        checkpoint()

    async def mdns(self, ips, own, found) -> None:
        assert own == OWN
        found.update({ip: n for ip, n in self.mdns_names.items() if ip in ips})

    def resolver(self, ip: str):
        if ip in self.dns:
            return (self.dns[ip], [], [ip])
        raise OSError("no name")

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    async def scan(self, confirm_away: Any = True, devices=()) -> dict[str, Any]:
        return await discovery.scan_network(
            confirm_away,
            devices=list(devices),
            route_probe=lambda: self.route,
            local_ip_for=lambda _gw: OWN,
            reader=self.files.get,
            probe=self.probe,
            mdns=self.mdns,
            resolver=self.resolver,
            sleep=self.sleep,
            clock=lambda: self.clock[0],
        )


@pytest.fixture
def runtime(decky_env) -> str:
    return decky_env.DECKY_PLUGIN_RUNTIME_DIR


async def test_scan_end_to_end(runtime) -> None:
    h = Harness(
        runtime,
        [
            ("192.168.1.20", mac(1), "wlan0"),
            ("192.168.1.30", mac(2), "wlan0"),
            ("192.168.1.40", mac(3), "wlan0"),
            (GW, mac(4), "wlan0"),
            ("192.168.1.60", mac(5), "eth0"),  # other interface
            ("198.51.100.7", mac(6), "wlan0"),  # outside the target set
        ],
        mdns={"192.168.1.20": "gamingpc"},
        dns={"192.168.1.20": "pc.lan", "192.168.1.30": "nas.lan"},
    )
    result = await h.scan()
    assert result["ok"] is True
    assert (result["probed"], result["found"], result["gateway"]) == (253, 4, GW)
    assert "new" not in result
    assert result["named"] == 2
    assert result["duration_ms"] == 0
    assert h.sleeps == [discovery.ARP_SETTLE]
    by_mac = {n["mac"]: n for n in result["neighbours"]}
    assert set(by_mac) == {mac(1), mac(2), mac(3), mac(4)}
    assert by_mac[mac(1)] == {
        "ip": "192.168.1.20",
        "mac": mac(1),
        "iface": "wlan0",
        "hostname": "gamingpc",
        "name_source": "mdns",
    }
    assert (by_mac[mac(2)]["hostname"], by_mac[mac(2)]["name_source"]) == ("nas.lan", "dns")
    for unnamed in (mac(3), mac(4)):
        assert by_mac[unnamed]["hostname"] is None and by_mac[unnamed]["name_source"] is None
    assert list(Path(runtime).iterdir()) == []  # nothing stored


async def test_route_change_mid_scan_aborts_and_cools_down(runtime) -> None:
    h = Harness(runtime)

    def change() -> None:
        h.route = {"iface": "wlan0", "gateway": "192.168.1.254"}

    h.on_probe = change
    assert await h.scan() == {"ok": False, "error": discovery.NETWORK_CHANGED}
    h.route = dict(ROUTE)
    assert (await h.scan())["retry_in"] == 30


async def test_route_lost_mid_scan_aborts(runtime) -> None:
    h = Harness(runtime)
    h.on_probe = lambda: setattr(h, "route", None)
    assert (await h.scan())["error"] == discovery.NETWORK_CHANGED


async def test_needs_confirm_sends_nothing(runtime) -> None:
    h = Harness(runtime)
    for confirm in (False, "yes", 1, None):
        result = await h.scan(confirm_away=confirm, devices=[device(1)])
        assert result == {
            "ok": False,
            "needs_confirm": True,
            "gateway": GW,
            "error": discovery.CONFIRM_AWAY,
        }
    other_home = [device(1, home_gateway="192.0.2.1")]
    assert (await h.scan(confirm_away=False, devices=other_home))["needs_confirm"] is True
    assert h.probed == []
    assert (await h.scan(confirm_away=False, devices=[device(1, home_gateway=GW)]))["ok"]


async def test_target_errors_skip_confirm_and_cooldown(runtime) -> None:
    h = Harness(runtime)
    h.route = None
    assert await h.scan() == {"ok": False, "error": discovery.NO_NETWORK}
    h.route = {"iface": "wg0", "gateway": GW}
    assert (await h.scan(confirm_away=False))["error"] == discovery.VPN_REFUSED
    h.route = dict(ROUTE)
    assert (await h.scan())["ok"]
    assert len(h.probed) == 1


async def test_busy_while_running(runtime) -> None:
    h = Harness(runtime)
    h.gate = asyncio.Event()
    first = asyncio.ensure_future(h.scan())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert await h.scan() == {"ok": False, "error": discovery.BUSY, "busy": True}
    h.gate.set()
    assert (await first)["ok"] is True
    assert len(h.probed) == 1


async def test_cooldown_and_retry_in(runtime) -> None:
    h = Harness(runtime)
    assert (await h.scan())["ok"]
    h.clock[0] += 10
    assert await h.scan() == {
        "ok": False,
        "error": "Scanned a moment ago — try again in 20 s",
        "retry_in": 20,
    }
    h.clock[0] += 19.5
    assert (await h.scan())["retry_in"] == 1
    h.clock[0] += 0.6
    assert (await h.scan())["ok"]


async def test_cancel_is_sync_and_starts_no_cooldown(runtime) -> None:
    h = Harness(runtime)
    h.gate = asyncio.Event()
    assert discovery.cancel() is False
    running = asyncio.ensure_future(h.scan())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert discovery.cancel() is True
    assert await running == {"ok": False, "error": discovery.CANCELLED, "cancelled": True}
    assert discovery.cancel() is False
    h.gate = None
    assert (await h.scan())["ok"] is True  # no cooldown after a cancel


async def test_caller_cancellation_propagates(runtime) -> None:
    h = Harness(runtime)
    h.gate = asyncio.Event()
    running = asyncio.ensure_future(h.scan())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert discovery._state.task is None


async def test_probe_socket_failure_is_reported_without_cooldown(runtime, caplog) -> None:
    h = Harness(runtime)

    async def broken(*_a) -> None:
        raise OSError(errno.EMFILE, "Too many open files")

    h.probe = broken  # type: ignore[method-assign]
    with caplog.at_level("ERROR", logger="decky-test"):
        assert await h.scan() == {"ok": False, "error": discovery.START_FAILED}
    assert any("could not start" in r.getMessage() for r in caplog.records)
    h.probe = Harness(runtime).probe  # type: ignore[method-assign]
    assert (await h.scan())["ok"] is True  # no cooldown


async def test_route_change_during_settle_aborts(runtime) -> None:
    h = Harness(runtime, [("192.168.1.20", mac(1), "wlan0")])

    async def settle(seconds: float) -> None:
        h.route = {"iface": "wlan0", "gateway": "192.168.1.254"}

    h.sleep = settle  # type: ignore[method-assign]
    assert await h.scan() == {"ok": False, "error": discovery.NETWORK_CHANGED}


async def test_route_change_while_naming_aborts(runtime) -> None:
    h = Harness(runtime, [("192.168.1.20", mac(1), "wlan0")])

    async def mdns(ips, own, found) -> None:
        h.route = None

    h.mdns = mdns  # type: ignore[method-assign]
    assert await h.scan() == {"ok": False, "error": discovery.NETWORK_CHANGED}


async def test_reverse_lookups_are_bounded(runtime, monkeypatch) -> None:
    entries = [(f"192.168.1.{i}", f"aa:bb:cc:dd:ee:{i:02x}", "wlan0") for i in range(2, 42)]
    h = Harness(runtime, entries)
    active = peak = 0

    async def lookup(ip, timeout=None, resolver=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return None

    monkeypatch.setattr(netinfo, "reverse_lookup", lookup)
    assert (await h.scan())["found"] == 40
    assert peak == discovery.MAX_IN_FLIGHT


async def test_cancel_is_false_once_cancelling(runtime) -> None:
    h = Harness(runtime)
    h.gate = asyncio.Event()
    running = asyncio.ensure_future(h.scan())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert discovery.cancel() is True
    assert discovery.cancel() is False  # already cancelling
    assert (await running)["cancelled"] is True


async def test_budget_overrun_before_arp_is_an_error(runtime, monkeypatch) -> None:
    monkeypatch.setattr(discovery, "SCAN_BUDGET", 0.01)
    h = Harness(runtime)
    h.gate = asyncio.Event()  # never set
    assert await h.scan() == {"ok": False, "error": discovery.TOO_SLOW}
    assert (await h.scan())["retry_in"] == 30


async def test_budget_overrun_while_naming_returns_partial(runtime, monkeypatch) -> None:
    monkeypatch.setattr(discovery, "SCAN_BUDGET", 0.01)
    h = Harness(runtime, [("192.168.1.20", mac(1), "wlan0"), ("192.168.1.30", mac(2), "wlan0")])

    async def slow_mdns(ips, own, found) -> None:
        found["192.168.1.20"] = "gamingpc"
        await asyncio.Event().wait()

    h.mdns = slow_mdns  # type: ignore[method-assign]
    result = await h.scan()
    assert result["ok"] is True and result["found"] == 2 and result["named"] == 1


async def test_mdns_and_rdns_failures_do_not_fail_the_scan(runtime) -> None:
    h = Harness(runtime, [("192.168.1.20", mac(1), "wlan0")])

    async def broken(*_a) -> None:
        raise RuntimeError("boom")

    h.mdns = broken  # type: ignore[method-assign]
    h.resolver = lambda _ip: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
    result = await h.scan()
    assert result["ok"] is True and result["named"] == 0


async def test_rdns_names_are_sanitised(runtime) -> None:
    h = Harness(
        runtime,
        [("192.168.1.20", mac(1), "wlan0")],
        dns={"192.168.1.20": "evil‮​pc\n.lan"},
    )
    result = await h.scan()
    assert result["neighbours"][0]["hostname"] == "evilpc .lan"


# --------------------------------------------------------------------------- Plugin


async def test_plugin_callables_tolerate_extra_args(decky_env, sandbox, monkeypatch) -> None:
    plugin = main.Plugin()
    assert await plugin.cancel_scan("extra", 1) == {"ok": True, "cancelled": False}
    assert (await plugin.find_host("not a host!", "extra"))["error"] == discovery.FIND_BAD_INPUT
    assert (await plugin.find_host())["error"] == discovery.FIND_BAD_INPUT
    assert await plugin.neighbours("extra") == []
    assert await plugin.scan_network(False, "extra") == {
        "ok": False,
        "error": discovery.NO_NETWORK,
    }
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    monkeypatch.setattr(discovery, "local_ip", lambda _gw: OWN)
    monkeypatch.setattr(discovery, "iface_addr", lambda _iface: OWN)
    result = await plugin.scan_network()
    assert result["needs_confirm"] is True and result["gateway"] == GW


async def test_plugin_scan_and_unload_never_yields(decky_env, sandbox, monkeypatch) -> None:
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    monkeypatch.setattr(discovery, "local_ip", lambda _gw: OWN)
    monkeypatch.setattr(discovery, "iface_addr", lambda _iface: OWN)
    started = asyncio.Event()

    async def hanging_probe(targets, checkpoint, sleep, own_ip) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(discovery, "udp_probe", hanging_probe)
    plugin = main.Plugin()
    await plugin.save_devices([device(1, home_gateway=GW)])
    running = asyncio.ensure_future(plugin.scan_network(False))
    await started.wait()
    coro = plugin._unload()
    with pytest.raises(StopIteration):
        coro.send(None)
    assert await asyncio.wait_for(running, 1) == {
        "ok": False,
        "error": discovery.CANCELLED,
        "cancelled": True,
    }


async def test_plugin_cancel_scan(decky_env, sandbox, monkeypatch) -> None:
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    monkeypatch.setattr(discovery, "local_ip", lambda _gw: OWN)
    monkeypatch.setattr(discovery, "iface_addr", lambda _iface: OWN)
    started = asyncio.Event()

    async def hanging_probe(targets, checkpoint, sleep, own_ip) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(discovery, "udp_probe", hanging_probe)
    plugin = main.Plugin()
    running = asyncio.ensure_future(plugin.scan_network(True))
    await started.wait()
    assert await plugin.cancel_scan() == {"ok": True, "cancelled": True}
    assert (await running)["cancelled"] is True


async def test_plugin_neighbours_is_the_plain_arp_list(decky_env, sandbox) -> None:
    (sandbox["fake"] / "arp").write_text(arp(("192.168.1.20", mac(1), "wlan0")))
    netinfo._hostname_cache["192.168.1.20"] = ("pc.lan", float("inf"))
    assert await main.Plugin().neighbours() == [
        {"ip": "192.168.1.20", "mac": mac(1), "iface": "wlan0", "hostname": "pc.lan"}
    ]


# --------------------------------------------------------------------------- find


class Finder:
    """Injected route, ARP, resolver, sender, sleep and clock for ``find_host``."""

    def __init__(self, arp_entries=(), *, resolved=None, rdns=None) -> None:
        self.files = {
            netinfo.PROC_ROUTE: routes(default_line(), onlink("wlan0", "192.168.1.0/24")),
            netinfo.PROC_ARP: arp(*arp_entries),
        }
        self.route: dict[str, str] | None = dict(ROUTE)
        self.resolved = resolved or {}
        self.rdns = rdns or {}
        self.resolves: list[tuple[str, float]] = []
        self.sent: list[tuple[str, str]] = []
        self.sleeps: list[float] = []
        self.clock = [0.0]
        self.answer_after: tuple[int, tuple[str, str, str]] | None = None
        self.gate: asyncio.Event | None = None

    async def resolve(self, host: str, timeout: float | None = None) -> str | None:
        self.resolves.append((host, timeout))
        if self.gate is not None:
            await self.gate.wait()
        return self.resolved.get(host)

    def send(self, ip: str, own: str) -> bool:
        self.sent.append((ip, own))
        return True

    def resolver(self, ip: str):
        if ip in self.rdns:
            return (self.rdns[ip], [], [ip])
        raise OSError("no name")

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock[0] += seconds
        if self.answer_after and len(self.sleeps) == self.answer_after[0]:
            self.files[netinfo.PROC_ARP] = arp(self.answer_after[1])

    async def find(self, address: Any) -> dict[str, Any]:
        return await discovery.find_host(
            address,
            route_probe=lambda: self.route,
            local_ip_for=lambda _gw: OWN,
            iface_addr_for=lambda _iface: OWN,
            reader=self.files.get,
            resolve=self.resolve,
            send=self.send,
            resolver=self.resolver,
            sleep=self.sleep,
            clock=lambda: self.clock[0],
        )


@pytest.mark.parametrize(
    "address",
    [None, 42, "", "   ", "a" * 254, "not a host!", "-bad.lan", "fe80::1", "2001:db8::1", "1.2.3"],
)
async def test_find_bad_input(address) -> None:
    f = Finder()
    assert await f.find(address) == {"ok": False, "error": discovery.FIND_BAD_INPUT}
    assert f.sent == [] and f.resolves == []


async def test_find_unresolvable_name() -> None:
    f = Finder()
    assert await f.find("gaming-pc.lan") == {"ok": False, "error": discovery.FIND_UNRESOLVED}
    assert f.resolves == [("gaming-pc.lan", 2.0)] and f.sent == []


@pytest.mark.parametrize(
    "ip", ["192.168.2.20", "198.51.100.7", "10.0.0.5", "192.0.2.10", "169.254.1.1"]
)
async def test_find_off_link_sends_nothing(ip) -> None:
    f = Finder()
    assert await f.find(ip) == {"ok": False, "error": discovery.FIND_OFF_LINK}
    assert f.sent == []


async def test_find_resolved_name_off_link_sends_nothing() -> None:
    f = Finder(resolved={"far.example": "198.51.100.7"})
    assert (await f.find("far.example"))["error"] == discovery.FIND_OFF_LINK
    assert f.sent == []


async def test_find_uses_the_real_prefix_not_a_slash_24() -> None:
    f = Finder([("192.168.0.20", mac(2), "wlan0")])
    f.files[netinfo.PROC_ROUTE] = routes(default_line(), onlink("wlan0", "192.168.0.0/23"))
    assert (await f.find("192.168.0.20"))["ok"] is True
    f.files[netinfo.PROC_ROUTE] = routes(default_line(), onlink("wlan0", "192.168.1.0/25"))
    assert (await f.find("192.168.1.200"))["error"] == discovery.FIND_OFF_LINK


async def test_find_own_network_and_broadcast_addresses() -> None:
    f = Finder()
    assert await f.find(OWN) == {"ok": False, "error": discovery.FIND_OWN}
    assert (await f.find("192.168.1.0"))["error"] == discovery.FIND_NOT_A_HOST
    assert (await f.find("192.168.1.255"))["error"] == discovery.FIND_NOT_A_HOST
    assert f.sent == []


async def test_find_arp_hit_sends_nothing() -> None:
    f = Finder([("192.168.1.20", mac(1), "wlan0")], rdns={"192.168.1.20": "pc.lan"})
    assert await f.find("192.168.1.20") == {
        "ok": True,
        "ip": "192.168.1.20",
        "mac": mac(1),
        "name": "pc.lan",
        "name_source": "dns",
    }
    assert f.sent == [] and f.sleeps == []


async def test_find_arp_entry_on_another_interface_does_not_count() -> None:
    f = Finder([("192.168.1.20", mac(1), "eth0")])
    assert (await f.find("192.168.1.20"))["error"] == discovery.FIND_NO_ANSWER
    assert f.sent == [("192.168.1.20", OWN)]


async def test_find_one_send_then_entry_appears() -> None:
    f = Finder()
    f.answer_after = (3, ("192.168.1.20", mac(1), "wlan0"))
    result = await f.find("192.168.1.20")
    assert result == {
        "ok": True,
        "ip": "192.168.1.20",
        "mac": mac(1),
        "name": None,
        "name_source": None,
    }
    assert f.sent == [("192.168.1.20", OWN)]
    assert f.sleeps == [0.25, 0.25, 0.25]


async def test_find_timeout_is_no_answer() -> None:
    f = Finder()
    assert await f.find("192.168.1.20") == {"ok": False, "error": discovery.FIND_NO_ANSWER}
    assert f.sent == [("192.168.1.20", OWN)]
    assert f.sleeps == [0.25] * 8 and f.clock[0] == 2.0


async def test_find_send_setup_failure() -> None:
    f = Finder()

    def broken(_ip: str, _own: str) -> bool:
        raise OSError(errno.EMFILE, "Too many open files")

    f.send = broken  # type: ignore[method-assign]
    assert await f.find("192.168.1.20") == {"ok": False, "error": discovery.FIND_START_FAILED}


async def test_find_hostname_uses_typed_name() -> None:
    f = Finder(
        [("192.168.1.20", mac(1), "wlan0")],
        resolved={"Gaming-PC.lan.": "192.168.1.20"},
        rdns={"192.168.1.20": "other.lan"},
    )
    result = await f.find("Gaming-PC.lan.")
    assert (result["ip"], result["name"], result["name_source"]) == (
        "192.168.1.20",
        "Gaming-PC.lan",
        "typed",
    )


async def test_find_rdns_name_is_sanitised() -> None:
    f = Finder([("192.168.1.20", mac(1), "wlan0")], rdns={"192.168.1.20": "evil\u202e\u200bpc.lan"})
    result = await f.find(" 192.168.1.20 ")
    assert (result["name"], result["name_source"]) == ("evilpc.lan", "dns")
    f = Finder([("192.168.1.30", mac(2), "wlan0")], rdns={"192.168.1.30": "\u200b"})
    result = await f.find("192.168.1.30")
    assert (result["name"], result["name_source"]) == (None, None)


@pytest.mark.parametrize(
    ("route", "error"),
    [
        (None, discovery.FIND_NO_NETWORK),
        ({"iface": "wg0", "gateway": GW}, discovery.FIND_VPN),
        ({"iface": "tailscale0", "gateway": GW}, discovery.FIND_VPN),
    ],
)
async def test_find_needs_a_home_route(route, error) -> None:
    f = Finder(resolved={"pc.lan": "192.168.1.20"})
    f.route = route
    assert await f.find("192.168.1.20") == {"ok": False, "error": error}
    assert await f.find("pc.lan") == {"ok": False, "error": error}
    assert f.sent == [] and f.resolves == []


async def test_find_refuses_a_public_network() -> None:
    f = Finder()
    f.files[netinfo.PROC_ROUTE] = routes(onlink("wlan0", "198.51.100.0/24"))
    result = await discovery.find_host(
        "198.51.100.20",
        route_probe=lambda: ROUTE,
        local_ip_for=lambda _gw: "198.51.100.5",
        reader=f.files.get,
        send=f.send,
    )
    assert result == {"ok": False, "error": discovery.FIND_NOT_HOME}
    assert f.sent == []


async def test_find_busy_and_independent_of_the_scan(runtime) -> None:
    f = Finder(resolved={"pc.lan": "192.168.1.20"})
    f.gate = asyncio.Event()
    first = asyncio.ensure_future(f.find("pc.lan"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert await f.find("192.168.1.30") == {
        "ok": False,
        "error": discovery.FIND_BUSY,
        "busy": True,
    }
    h = Harness(runtime)
    assert (await h.scan())["ok"] is True  # a find doesn't block a scan
    discovery._state.completed_at = h.clock[0]
    f.gate.set()
    assert (await first)["error"] == discovery.FIND_NO_ANSWER
    f.gate = None
    f.files[netinfo.PROC_ARP] = arp(("192.168.1.20", mac(1), "wlan0"))
    assert (await f.find("pc.lan"))["ok"] is True  # no cooldown


async def test_cancel_find_is_sync() -> None:
    f = Finder(resolved={"pc.lan": "192.168.1.20"})
    f.gate = asyncio.Event()
    assert discovery.cancel_find() is False
    running = asyncio.ensure_future(f.find("pc.lan"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert discovery.cancel() is False  # cancel_scan's meaning is unchanged
    assert discovery.cancel_find() is True
    assert discovery.cancel_find() is False
    assert await running == {"ok": False, "error": discovery.FIND_CANCELLED, "cancelled": True}
    assert discovery._state.find_task is None


def test_send_one_reuses_the_probe_socket() -> None:
    fake = FakeUdp()
    assert discovery.send_one("192.168.1.20", OWN, lambda: fake) is True
    assert fake.sent == [(b"", ("192.168.1.20", 9))]
    assert (socket.SOL_SOCKET, socket.SO_DONTROUTE, 1) in fake.options
    assert fake.bound == (OWN, 0) and fake.blocking is False and fake.closed
    failing = FakeUdp(fail={"192.168.1.20": OSError(errno.EHOSTUNREACH, "x")})
    assert discovery.send_one("192.168.1.20", OWN, lambda: failing) is False
    assert failing.closed


async def test_plugin_find_and_unload_never_yields(decky_env, sandbox, monkeypatch) -> None:
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    monkeypatch.setattr(discovery, "local_ip", lambda _gw: OWN)
    monkeypatch.setattr(discovery, "iface_addr", lambda _iface: OWN)
    sent = []
    monkeypatch.setattr(discovery, "send_one", lambda ip, own: sent.append(ip))
    started = asyncio.Event()

    async def hanging_resolve(host, timeout=None):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(netinfo, "resolve_host", hanging_resolve)
    plugin = main.Plugin()
    running = asyncio.ensure_future(plugin.find_host("pc.lan", "extra"))
    await started.wait()
    coro = plugin._unload()
    with pytest.raises(StopIteration):
        coro.send(None)
    assert await asyncio.wait_for(running, 1) == {  # fails, not hangs, if not cancelled
        "ok": False,
        "error": discovery.FIND_CANCELLED,
        "cancelled": True,
    }
    assert sent == []
