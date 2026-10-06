import asyncio
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from helpers import HOME_ROUTE, ROUTE_HEADER, route_line, write_network

from wake_dispatch import netinfo


def test_parse_routes_keeps_default_gateways_only() -> None:
    text = (
        ROUTE_HEADER
        + route_line("eth0", "00000000", "0101A8C0", "0003", 100)
        + route_line("eth0", "0001A8C0", "00000000", "0001", 100)  # LAN route, no gateway flag
        + route_line("wlan0", "00000000", "010200C0", "0001", 50)  # no RTF_GATEWAY
        + route_line("wlan0", "00000000", "010200C0", "0002", 50)  # not RTF_UP
        + "garbage line\n"
    )
    assert netinfo.parse_routes(text) == [
        {"iface": "eth0", "gateway": "192.168.1.1", "metric": 100}
    ]


def test_default_route_picks_lowest_metric(sandbox) -> None:
    routes = (
        ROUTE_HEADER
        + route_line("eth0", "00000000", "0101A8C0", "0003", 100)
        + route_line("wlan0", "00000000", "010200C0", "0003", 600)
    )
    write_network(sandbox["fake"], routes, {"eth0": "up", "wlan0": "up"})
    assert netinfo.default_route() == {"iface": "eth0", "gateway": "192.168.1.1"}


def test_default_route_skips_down_interface(sandbox) -> None:
    routes = (
        ROUTE_HEADER
        + route_line("eth0", "00000000", "0101A8C0", "0003", 100)
        + route_line("wlan0", "00000000", "010200C0", "0003", 600)
    )
    write_network(sandbox["fake"], routes, {"eth0": "down", "wlan0": "unknown"})
    assert netinfo.default_route() == {"iface": "wlan0", "gateway": "192.0.2.1"}


@pytest.mark.parametrize("state", ["down", "dormant", None])
def test_operstate_not_up_means_no_route(sandbox, state) -> None:
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": state} if state else {})
    assert netinfo.default_route() is None


def test_no_route_file(sandbox) -> None:
    assert netinfo.default_route() is None


def test_injected_reader() -> None:
    files = {"/r": HOME_ROUTE, "/s/wlan0/operstate": "up\n"}
    assert netinfo.default_route("/r", "/s", files.get) == {
        "iface": "wlan0",
        "gateway": "192.168.1.1",
    }


def test_interface_name_cannot_escape() -> None:
    assert not netinfo.interface_up("../etc", reader=lambda _p: "up")


async def test_wait_for_network_polls_until_route() -> None:
    answers = iter([None, None, {"iface": "eth0", "gateway": "192.168.1.1"}])
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    route = await netinfo.wait_for_network(10, probe=lambda: next(answers), sleep=fake_sleep)
    assert route == {"iface": "eth0", "gateway": "192.168.1.1"}
    assert sleeps == [1.0, 1.0]


async def test_wait_for_network_times_out_without_real_waiting() -> None:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    assert await netinfo.wait_for_network(2.5, probe=lambda: None, sleep=fake_sleep) is None
    assert sleeps == [1.0, 1.0, 0.5]


def test_read_boot_id(sandbox) -> None:
    assert netinfo.read_boot_id() is None
    (sandbox["fake"] / "boot_id").write_text("1234-abcd\n")
    assert netinfo.read_boot_id() == "1234-abcd"


ARP = (
    "IP address       HW type     Flags       HW address            Mask     Device\n"
    "192.168.1.20     0x1         0x2         AA:BB:CC:DD:EE:01     *        wlan0\n"
    "192.168.1.21     0x1         0x0         aa:bb:cc:dd:ee:02     *        wlan0\n"
    "192.168.1.22     0x1         0x2         00:00:00:00:00:00     *        wlan0\n"
    "192.168.1.23     0x1         0x6         aa:bb:cc:dd:ee:03     *        eth0\n"
    "short line\n"
)


def test_parse_arp_complete_only() -> None:
    assert netinfo.parse_arp(ARP) == [
        {"ip": "192.168.1.20", "mac": "aa:bb:cc:dd:ee:01", "iface": "wlan0"},
        {"ip": "192.168.1.23", "mac": "aa:bb:cc:dd:ee:03", "iface": "eth0"},
    ]


async def test_neighbours_with_hostnames(sandbox) -> None:
    (sandbox["fake"] / "arp").write_text(ARP)

    def resolver(ip: str):
        if ip == "192.168.1.20":
            return ("gaming-pc.example", [], [ip])
        raise socket.herror(1, "Unknown host")

    result = await netinfo.neighbours(resolver=resolver)
    assert [n["hostname"] for n in result] == ["gaming-pc.example", None]


def test_default_timeouts_pinned() -> None:
    assert netinfo.STATUS_TIMEOUT == 1.0
    assert netinfo.REVERSE_DNS_TIMEOUT <= 0.5


async def test_neighbours_lookups_run_concurrently(sandbox) -> None:
    # Both lookups must be in flight at once to get past the barrier.
    (sandbox["fake"] / "arp").write_text(ARP)
    barrier = threading.Barrier(2, timeout=2)

    def resolver(ip: str):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            raise OSError("lookups ran one at a time") from None
        return (f"host-{ip.rsplit('.', 1)[1]}.example", [], [ip])

    result = await netinfo.neighbours(resolver=resolver, timeout=3)
    assert [n["hostname"] for n in result] == ["host-20.example", "host-23.example"]


async def test_reverse_dns_timeout_does_not_block_loop() -> None:
    release = threading.Event()
    started = threading.Event()

    def stuck_resolver(_ip: str):
        started.set()
        release.wait(5)
        return ("late.example", [], [])

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    beat = asyncio.create_task(heartbeat())
    try:
        names = await asyncio.gather(
            *(netinfo.reverse_lookup(f"192.0.2.{i}", 0.05, stuck_resolver) for i in range(6))
        )
    finally:
        beat.cancel()
        release.set()
    assert names == [None] * 6
    assert started.is_set()
    assert ticks > 1  # the loop kept running while lookups were stuck
    assert "192.0.2.0" not in netinfo._hostname_cache  # timeouts aren't cached


async def test_reverse_dns_uses_dedicated_pool_not_default_executor() -> None:
    class NoDefault(ThreadPoolExecutor):
        def submit(self, *args, **kwargs):
            raise AssertionError("default executor used")

    loop = asyncio.get_running_loop()
    default = NoDefault(max_workers=1)
    loop.set_default_executor(default)
    threads: list[str] = []

    def resolver(ip: str):
        threads.append(threading.current_thread().name)
        return ("pc.example", [], [ip])

    assert await netinfo.reverse_lookup("192.0.2.9", 1.0, resolver) == "pc.example"
    assert threads and threads[0].startswith("wd-rdns")
    assert netinfo._rdns_pool is not None and netinfo._rdns_pool._max_workers == 4


async def test_reverse_dns_cache() -> None:
    calls: list[str] = []
    now = [100.0]

    def resolver(ip: str):
        calls.append(ip)
        return ("pc.example", [], [ip])

    for _ in range(2):
        assert await netinfo.reverse_lookup("192.0.2.5", 1.0, resolver, clock=lambda: now[0])
    assert calls == ["192.0.2.5"]
    now[0] += netinfo.HOSTNAME_TTL + 1
    await netinfo.reverse_lookup("192.0.2.5", 1.0, resolver, clock=lambda: now[0])
    assert calls == ["192.0.2.5"] * 2


def test_shutdown_resolver_is_idempotent() -> None:
    netinfo._rdns_executor()
    netinfo.shutdown_resolver()
    netinfo.shutdown_resolver()
    assert netinfo._rdns_pool is None


async def test_real_dns_guard_is_active() -> None:
    with pytest.raises(AssertionError):
        socket.gethostbyaddr("192.0.2.1")
    with pytest.raises(AssertionError):
        socket.getaddrinfo("pc.invalid", 22)


async def test_neighbours_empty_without_arp_file(sandbox) -> None:
    assert await netinfo.neighbours() == []


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False
        self.waited = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True


async def test_status_awake_asleep_unknown() -> None:
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    open_port = server.sockets[0].getsockname()[1]

    async def opener(host, port):
        if port == 1:
            raise ConnectionRefusedError(111, "Connection refused")
        return await asyncio.open_connection(host, port)

    try:
        devices = [
            {"id": "awake", "host": "127.0.0.1", "status_port": open_port},
            {"id": "asleep", "host": "127.0.0.1", "status_port": 1},
            {"id": "no-host", "host": None, "status_port": 22},
            {"id": "no-port", "host": "127.0.0.1", "status_port": None},
        ]
        result = await netinfo.status_map(devices, None, timeout=1.0, opener=opener)
        assert result == {
            "awake": "awake",
            "asleep": "asleep",
            "no-host": "unknown",
            "no-port": "unknown",
        }
        only = await netinfo.status_map(devices, ["awake", "missing"], timeout=1.0)
        assert only == {"awake": "awake"}
    finally:
        server.close()
        await server.wait_closed()


async def test_status_checks_run_concurrently_and_close_writers() -> None:
    # Each connect only completes once all three have started.
    all_started = asyncio.Event()
    started = 0
    writers: list[FakeWriter] = []

    async def opener(_host, _port):
        nonlocal started
        started += 1
        if started == 3:
            all_started.set()
        await all_started.wait()
        writer = FakeWriter()
        writers.append(writer)
        return object(), writer

    devices = [{"id": f"pc-{i}", "host": "192.0.2.1", "status_port": 22} for i in range(3)]
    result = await netinfo.status_map(devices, None, timeout=1.0, opener=opener)
    assert result == {"pc-0": "awake", "pc-1": "awake", "pc-2": "awake"}
    assert len(writers) == 3
    assert all(w.closed and w.waited for w in writers)


async def test_status_lookup_failure_and_timeout() -> None:
    async def gai(_h, _p):
        raise socket.gaierror(-2, "Name or service not known")

    async def hang(_h, _p):
        await asyncio.sleep(10)

    assert await netinfo.check_status("pc.invalid", 22, opener=gai) == "unknown"
    assert await netinfo.check_status("192.0.2.1", 22, timeout=0.01, opener=hang) == "asleep"
