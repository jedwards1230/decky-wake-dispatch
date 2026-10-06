"""Shared fixture data and builders. Placeholder values only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROUTE_HEADER = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
)


def route_line(iface: str, dest: str, gateway: str, flags: str, metric: int) -> str:
    return f"{iface}\t{dest}\t{gateway}\t{flags}\t0\t0\t{metric}\t00000000\t0\t0\t0\n"


# 192.168.1.1 little-endian = 0101A8C0; 192.0.2.1 = 010200C0
HOME_ROUTE = ROUTE_HEADER + route_line("wlan0", "00000000", "0101A8C0", "0003", 600)


def write_network(fake: Path, routes: str | None, states: dict[str, str] | None = None) -> None:
    if routes is not None:
        (fake / "route").write_text(routes)
    for iface, state in (states or {}).items():
        (fake / "sys-net" / iface).mkdir(exist_ok=True)
        (fake / "sys-net" / iface / "operstate").write_text(state + "\n")


def device(n: int = 1, **overrides: Any) -> dict[str, Any]:
    base = {
        "id": f"pc-{n}",
        "name": f"Gaming PC {n}",
        "mac": f"aa:bb:cc:dd:ee:{n:02x}",
        "broadcast": "192.168.1.255",
        "port": 9,
        "host": None,
        "status_port": None,
        "secureon": None,
        "auto": [],
        "home_gateway": None,
    }
    base.update(overrides)
    return base


class Recorder:
    """In-memory state + emit sink for Dispatcher tests."""

    def __init__(self, devices: list[dict[str, Any]] | None = None) -> None:
        self.devices = devices or []
        self.state: dict[str, Any] = {
            "boot_id": None,
            "last": None,
            "automation": {"boot": None, "resume": None},
        }
        self.saves = 0
        self.events: list[tuple[str, dict[str, Any]]] = []

    def load_devices(self) -> list[dict[str, Any]]:
        return [dict(d) for d in self.devices]

    def load_state(self) -> dict[str, Any]:
        import copy

        return copy.deepcopy(self.state)

    def save_state(self, state: dict[str, Any]) -> None:
        self.saves += 1
        self.state = state

    async def emit(self, event: str, record: dict[str, Any]) -> None:
        self.events.append((event, record))


class FakeSocket:
    """Records what a real UDP socket would have been asked to do."""

    def __init__(self, log: list[dict[str, Any]], fail: BaseException | None = None) -> None:
        self.log = log
        self.fail = fail
        self.options: list[tuple[int, int, int]] = []
        self.closed = False

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        if self.fail is not None:
            raise self.fail
        self.log.append({"data": data, "address": address, "options": list(self.options)})
        return len(data)

    def close(self) -> None:
        self.closed = True
