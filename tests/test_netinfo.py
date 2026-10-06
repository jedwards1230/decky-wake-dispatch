import asyncio
import errno
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from helpers import HOME_ROUTE, ROUTE_HEADER, route_line, write_network

from wake_dispatch import netinfo

HOME = {"iface": "wlan0", "gateway": "192.168.1.1"}
PY_MODULES = Path(__file__).resolve().parent.parent / "py_modules"


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


async def test_lookups_use_daemon_threads_not_an_executor() -> None:
    class NoDefault(ThreadPoolExecutor):
        def submit(self, *args, **kwargs):
            raise AssertionError("default executor used")

    loop = asyncio.get_running_loop()
    loop.set_default_executor(NoDefault(max_workers=1))
    seen: list[threading.Thread] = []

    def resolver(ip: str):
        seen.append(threading.current_thread())
        return ("pc.example", [], [ip])

    def forward(host: str) -> str:
        seen.append(threading.current_thread())
        return "192.0.2.9"

    assert await netinfo.reverse_lookup("192.0.2.9", 1.0, resolver) == "pc.example"
    assert await netinfo.resolve_host("pc.example", 1.0, forward) == "192.0.2.9"
    assert len(seen) == 2
    assert all(t.daemon and t.name == "wd-lookup" for t in seen)
    assert not hasattr(netinfo, "ThreadPoolExecutor")


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


async def test_shutdown_resolver_is_idempotent_and_closes_lookups() -> None:
    calls: list[str] = []

    def resolver(ip: str):
        calls.append(ip)
        return ("pc.example", [], [ip])

    assert await netinfo.reverse_lookup("192.0.2.5", 1.0, resolver) == "pc.example"
    netinfo.shutdown_resolver()
    netinfo.shutdown_resolver()
    assert netinfo._hostname_cache == {}
    assert await netinfo.reverse_lookup("192.0.2.5", 1.0, resolver) is None
    assert await netinfo.resolve_host("pc.example", 1.0, lambda _h: "192.0.2.5") is None
    assert calls == ["192.0.2.5"]  # nothing ran after shutdown


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
            raise TimeoutError
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
    def gai(_h):
        raise socket.gaierror(-2, "Name or service not known")

    async def opener(_h, _p):
        raise AssertionError("no connect without an address")

    async def hang(_h, _p):
        await asyncio.sleep(10)

    assert await netinfo.check_status("pc.invalid", 22, opener=opener, resolver=gai) == "unknown"
    assert await netinfo.check_status("192.0.2.1", 22, timeout=0.01, opener=hang) == "asleep"


def _raiser(exc: BaseException):
    async def opener(_h, _p):
        raise exc

    return opener


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"), "awake"),
        (OSError(errno.ENETUNREACH, "Network is unreachable"), "unknown"),
        (OSError(errno.EHOSTUNREACH, "No route to host"), "unknown"),
        (OSError(errno.ENETDOWN, "Network is down"), "unknown"),
        (OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address"), "unknown"),
        (TimeoutError(), "asleep"),
        (OSError(errno.ECONNRESET, "Connection reset"), "asleep"),
    ],
)
async def test_status_connect_error_mapping(exc, expected) -> None:
    assert await netinfo.check_status("192.0.2.1", 22, opener=_raiser(exc)) == expected


async def test_status_slow_lookup_is_unknown_not_asleep(monkeypatch) -> None:
    release = threading.Event()
    monkeypatch.setattr(netinfo, "STATUS_LOOKUP_TIMEOUT", 0.05)

    def slow(_h: str) -> str:
        release.wait(5)
        return "192.0.2.1"

    async def opener(_h, _p):
        raise AssertionError("no connect after a slow lookup")

    try:
        result = await netinfo.check_status("pc.example", 22, opener=opener, resolver=slow)
    finally:
        release.set()
    assert result == "unknown"
    assert "pc.example" not in netinfo._address_cache  # timeouts aren't cached


async def test_status_ip_literal_skips_lookup_and_name_connects_to_numeric_ip() -> None:
    targets: list[tuple[str, int]] = []
    looked_up: list[str] = []

    async def opener(host, port):
        targets.append((host, port))
        raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")

    def resolver(host: str) -> str:
        looked_up.append(host)
        return "192.0.2.44"

    assert await netinfo.check_status("192.0.2.7", 22, opener=opener, resolver=resolver) == "awake"
    assert looked_up == []
    devices = [{"id": "pc", "host": "pc.example", "status_port": 3389}]
    for _ in range(2):  # the second call is served from the address cache
        result = await netinfo.status_map(devices, None, opener=opener, resolver=resolver)
        assert result == {"pc": "awake"}
    assert looked_up == ["pc.example"]
    assert targets == [("192.0.2.7", 22), ("192.0.2.44", 3389), ("192.0.2.44", 3389)]


async def test_resolve_host_rules() -> None:
    assert await netinfo.resolve_host("192.0.2.1", 1.0, lambda _h: "x") == "192.0.2.1"
    assert await netinfo.resolve_host("", 1.0) is None
    assert await netinfo.resolve_host("v6.example", 1.0, lambda _h: "2001:db8::1") is None
    assert await netinfo.resolve_host("junk.example", 1.0, lambda _h: "not an ip") is None

    def boom(_h: str) -> str:
        raise OSError("resolver broke")

    assert await netinfo.resolve_host("broken.example", 1.0, boom) is None
    assert netinfo._address_cache["broken.example"][0] is None  # misses are cached briefly


async def test_default_status_resolver_uses_getaddrinfo_ipv4(monkeypatch) -> None:
    calls = []

    def fake_getaddrinfo(host, port, family=0, type=0, *rest):
        calls.append((host, family, type))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.30", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert await netinfo.resolve_host("pc.example", 1.0) == "192.0.2.30"
    assert calls == [("pc.example", socket.AF_INET, socket.SOCK_STREAM)]


async def test_lookup_bound_fails_fast(monkeypatch) -> None:
    monkeypatch.setattr(netinfo, "_lookup_slots", threading.BoundedSemaphore(1))
    release = threading.Event()

    def stuck(_ip: str):
        release.wait(5)
        return ("late.example", [], [])

    try:
        first = asyncio.create_task(netinfo.reverse_lookup("192.0.2.1", 1.0, stuck))
        await asyncio.sleep(0.01)
        loop = asyncio.get_running_loop()
        started = loop.time()
        assert await netinfo.reverse_lookup("192.0.2.2", 1.0, stuck) is None
        assert loop.time() - started < 0.5  # no free slot: didn't wait for the timeout
    finally:
        release.set()
    assert await first == "late.example"


async def test_late_answer_after_timeout_is_dropped() -> None:
    release = threading.Event()
    done = threading.Event()

    def late(_ip: str):
        release.wait(5)
        done.set()
        return ("late.example", [], [])

    assert await netinfo.reverse_lookup("192.0.2.3", 0.02, late) is None
    release.set()
    assert done.wait(2)
    await asyncio.sleep(0.05)  # the thread's call_soon_threadsafe runs; must not raise
    assert "192.0.2.3" not in netinfo._hostname_cache


async def test_reverse_lookup_names_are_sanitised() -> None:
    def resolver(ip: str):
        return ("evil‮gnp.exe​.example", [], [ip])

    assert await netinfo.reverse_lookup("192.0.2.4", 1.0, resolver) == "evilgnp.exe.example"


HANG_SCRIPT = """
import asyncio, sys, time
sys.path.insert(0, sys.argv[1])
from wake_dispatch import netinfo

async def main():
    hang = lambda _arg: time.sleep(30)
    assert await netinfo.reverse_lookup("192.0.2.1", 0.05, hang) is None
    assert await netinfo.resolve_host("pc.example", 0.05, hang) is None
    netinfo.shutdown_resolver()

asyncio.run(main())
"""


def test_hung_lookup_does_not_block_interpreter_exit(tmp_path) -> None:
    script = tmp_path / "hang.py"
    script.write_text(HANG_SCRIPT)
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(script), str(PY_MODULES)], timeout=20, capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()
    assert time.monotonic() - started < 5


def _arp_lines(count: int) -> str:
    header = "IP address       HW type     Flags       HW address            Mask     Device\n"
    return header + "".join(
        f"192.0.2.{i + 1}  0x1  0x2  aa:bb:cc:dd:ee:{i + 1:02x}  *  wlan0\n" for i in range(count)
    )


class _SlowReleaseSlots(threading.BoundedSemaphore):
    """Thread slots whose release lags, widening the slot hand-off window."""

    def release(self, n: int = 1) -> None:
        time.sleep(0.05)
        super().release(n)


async def test_neighbours_queue_beyond_the_thread_limit(sandbox, monkeypatch) -> None:
    (sandbox["fake"] / "arp").write_text(_arp_lines(12))
    # If a lookup delivered its answer before freeing its thread slot, the next
    # queued caller would find every slot taken and give up; the lagging release
    # makes that ordering bug fail every run instead of only under load.
    monkeypatch.setattr(netinfo, "_lookup_slots", _SlowReleaseSlots(netinfo.LOOKUP_THREADS))
    running = 0
    peak = 0
    lock = threading.Lock()

    def resolver(ip: str):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        with lock:
            running -= 1
        return (f"pc-{ip.rsplit('.', 1)[1]}.example", [], [ip])

    result = await netinfo.neighbours(resolver=resolver, timeout=10.0)
    assert [n["hostname"] for n in result] == [f"pc-{i}.example" for i in range(1, 13)]
    assert peak <= netinfo.LOOKUP_THREADS


async def test_queued_lookups_still_bounded_by_their_timeout(sandbox) -> None:
    (sandbox["fake"] / "arp").write_text(_arp_lines(12))
    release = threading.Event()

    def slow(_ip: str):
        release.wait(5)
        return ("late.example", [], [])

    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        result = await netinfo.neighbours(resolver=slow, timeout=0.1)
    finally:
        release.set()
    assert [n["hostname"] for n in result] == [None] * 12
    assert loop.time() - started < 1.0


async def test_status_waits_for_a_slot_while_the_picker_resolves() -> None:
    release = threading.Event()

    def busy(_ip: str):
        release.wait(5)
        return ("pc.example", [], [])

    async def opener(_h, _p):
        raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")

    lookups = [
        asyncio.create_task(netinfo.reverse_lookup(f"192.0.2.{i}", 1.0, busy))
        for i in range(netinfo.LOOKUP_THREADS)
    ]
    await asyncio.sleep(0.01)
    status = asyncio.create_task(
        netinfo.check_status("pc.example", 22, opener=opener, resolver=lambda _h: "192.0.2.50")
    )
    await asyncio.sleep(0.05)
    assert not status.done()  # queued, not failed
    release.set()
    assert await status == "awake"
    await asyncio.gather(*lookups)


@pytest.mark.parametrize(("route", "expected"), [(None, "unknown"), (HOME, "asleep")])
async def test_host_unreachable_depends_on_a_default_route(route, expected) -> None:
    exc = OSError(errno.EHOSTUNREACH, "No route to host")
    result = await netinfo.check_status(
        "192.0.2.1", 22, opener=_raiser(exc), route_probe=lambda: route
    )
    assert result == expected
    devices = [{"id": "pc", "host": "192.0.2.1", "status_port": 22}]
    assert await netinfo.status_map(
        devices, None, opener=_raiser(exc), route_probe=lambda: route
    ) == {"pc": expected}


async def test_host_unreachable_uses_the_real_route_probe(sandbox) -> None:
    exc = OSError(errno.EHOSTUNREACH, "No route to host")
    assert await netinfo.check_status("192.0.2.1", 22, opener=_raiser(exc)) == "unknown"
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    assert await netinfo.check_status("192.0.2.1", 22, opener=_raiser(exc)) == "asleep"


async def test_slow_close_is_bounded() -> None:
    class SlowClose(FakeWriter):
        async def wait_closed(self) -> None:
            await asyncio.sleep(10)

    async def opener(_h, _p):
        return object(), SlowClose()

    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await netinfo.check_status("192.0.2.1", 22, opener=opener) == "awake"
    assert loop.time() - started < netinfo.CLOSE_TIMEOUT + 0.2


async def test_thread_start_failure_restores_the_slot(monkeypatch) -> None:
    def refuse(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", refuse)
    for _ in range(netinfo.LOOKUP_THREADS + 2):
        assert await netinfo.reverse_lookup("192.0.2.1", 1.0, lambda ip: ("pc", [], [ip])) is None
    assert netinfo._lookup_slots._value == netinfo.LOOKUP_THREADS
    assert "192.0.2.1" not in netinfo._hostname_cache


def test_answer_after_the_loop_closed_is_dropped(monkeypatch) -> None:
    release = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))

    def gated(ip: str):
        try:
            release.wait(5)
            return ("pc.example", [], [ip])
        finally:
            finished.set()

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(netinfo.reverse_lookup("192.0.2.1", 0.05, gated)) is None
    finally:
        loop.close()
    release.set()
    assert finished.wait(2)
    for _ in range(100):  # the worker releases its slot right after trying to deliver
        if netinfo._lookup_slots._value == netinfo.LOOKUP_THREADS:
            break
        time.sleep(0.01)
    assert errors == []
    assert netinfo._lookup_slots._value == netinfo.LOOKUP_THREADS


async def test_name_caches_are_bounded(monkeypatch) -> None:
    monkeypatch.setattr(netinfo, "CACHE_MAX", 4)
    now = [0.0]
    for i in range(6):
        await netinfo.reverse_lookup(
            f"192.0.2.{i}", 1.0, lambda ip: ("pc", [], [ip]), clock=lambda: now[0]
        )
    assert list(netinfo._hostname_cache) == [f"192.0.2.{i}" for i in range(2, 6)]  # oldest out
    now[0] = netinfo.HOSTNAME_TTL + 1  # everything cached so far has expired
    await netinfo.reverse_lookup(
        "192.0.2.99", 1.0, lambda ip: ("pc", [], [ip]), clock=lambda: now[0]
    )
    assert list(netinfo._hostname_cache) == ["192.0.2.99"]  # expired entries pruned first
    for i in range(6):
        await netinfo.resolve_host(f"pc{i}.example", 1.0, lambda _h: "192.0.2.1")
    assert len(netinfo._address_cache) == 4
