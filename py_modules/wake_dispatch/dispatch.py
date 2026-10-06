"""The Dispatcher: which devices to wake, the packet burst, and the dispatch record.

Outcome rules (``DispatchRecord.outcome``):

- ``no_network``: no default route appeared within the trigger's network wait.
- ``skipped``: nothing was attempted - no devices selected / opted in, or every
  selected device was skipped (e.g. "Not on home network").
- ``sent``: every selected device got at least one packet out.
- ``failed``: no device got a packet out and at least one errored.
- ``partial``: anything else (some sent, others errored or were skipped). The
  reason says which: "Some devices couldn't be woken" if anything errored,
  otherwise "Some devices weren't on their home network" (when every skip was
  "Not on home network" or "Different network (same router address)"; else the generic
  "Some devices were skipped").

A device counts as ``sent`` if any packet of its burst was sent; if every
attempt failed it is ``error`` with the plain-language message of the last failure.

Order of work: a manual wake selects devices first (nothing to wake -> no wait),
then waits for a route. An automatic wake waits for a route first (the boot gate
must only record a boot once the network is up), then selects opted-in devices
and applies the home-network gate.

Home-network gate (automatic wakes only): a device with ``home_gateway`` set is
skipped "Not on home network" when the current gateway's IP differs. When the IP
matches, the device has a ``home_gateway_mac`` and the current router's MAC is
known (from ARP, read once per wake), a different MAC skips it "Different
network (same router address)". An unknown current MAC (ARP may not have the
router yet right after resume) falls back to the IP check alone.
"""

from __future__ import annotations

import asyncio
import errno
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any

from wake_dispatch import netinfo, packet
from wake_dispatch.log import get_logger

TRIGGERS = ("manual", "boot", "resume")
AUTO_TRIGGERS = ("boot", "resume")

# Send offsets in seconds from the start of the burst.
MANUAL_BURST: tuple[float, ...] = (0, 1, 2)
AUTO_BURST: tuple[float, ...] = (0, 2, 5, 10, 20)
# How long to wait for a default route before giving up.
NETWORK_WAIT: dict[str, float] = {"manual": 5, "boot": 60, "resume": 20}

NOT_HOME = "Not on home network"
OTHER_NETWORK = "Different network (same router address)"
NO_OPT_IN = "No devices opted in"
NO_DEVICES = "No devices configured"
NO_MATCH = "None of the chosen devices exist"
NO_NETWORK = "No network connection"
SOME_FAILED = "Some devices couldn't be woken"
SOME_NOT_HOME = "Some devices weren't on their home network"
SOME_SKIPPED = "Some devices were skipped"
ALL_FAILED = "Couldn't wake any device"
ALREADY_RUNNING = "Already running"

_ERRNO_MESSAGES = {
    errno.ENETUNREACH: "Couldn't reach the network",
    errno.ENETDOWN: "The network is down",
    errno.EHOSTUNREACH: "Couldn't reach the broadcast address",
    errno.EADDRNOTAVAIL: "The broadcast address isn't available on this network",
    errno.EACCES: "Broadcast not permitted",
    errno.EPERM: "Broadcast not permitted",
    errno.ENOBUFS: "The network is busy; try again",
    errno.EMSGSIZE: "The packet was too large to send",
}


def describe_error(exc: BaseException) -> str:
    """Turn an exception from sending into a short plain-language message."""
    if isinstance(exc, socket.gaierror):
        return "Address lookup failed"
    if isinstance(exc, OSError):
        message = _ERRNO_MESSAGES.get(exc.errno) if exc.errno is not None else None
        if message:
            return message
        return f"Couldn't send the wake packet: {exc.strerror or exc}"
    if isinstance(exc, ValueError):
        return f"Invalid device settings: {exc}"
    return f"Couldn't send the wake packet: {exc}"


def summarise(results: dict[str, dict[str, Any]]) -> tuple[str, str | None]:
    """Return ``(outcome, reason)`` for a set of per-device results (see module docstring)."""
    statuses = [r["status"] for r in results.values()]
    if not statuses:
        return "skipped", NO_DEVICES
    if all(s == "sent" for s in statuses):
        return "sent", None
    if all(s == "skipped" for s in statuses):
        reasons = {r.get("error") for r in results.values()}
        return "skipped", reasons.pop() if len(reasons) == 1 else None
    if "sent" not in statuses and "error" in statuses:
        errors = {r.get("error") for r in results.values() if r["status"] == "error"}
        if len(errors) == 1 and "skipped" not in statuses:
            return "failed", errors.pop()
        return "failed", ALL_FAILED
    if "error" in statuses:
        return "partial", SOME_FAILED
    skip_reasons = {r.get("error") for r in results.values() if r["status"] == "skipped"}
    not_home = skip_reasons <= {NOT_HOME, OTHER_NETWORK}
    return "partial", SOME_NOT_HOME if not_home else SOME_SKIPPED


class Dispatcher:
    """Runs wakes. All collaborators are injectable; ``None`` means the module default
    looked up at call time (so tests can patch module constants)."""

    def __init__(
        self,
        *,
        load_devices: Callable[[], list[dict[str, Any]]],
        load_state: Callable[[], dict[str, Any]],
        save_state: Callable[[dict[str, Any]], None],
        emit: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
        wait_for_network: Callable[[float], Awaitable[dict[str, str] | None]] | None = None,
        sender: Callable[[bytes, str, int], None] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        bursts: dict[str, tuple[float, ...]] | None = None,
        network_wait: dict[str, float] | None = None,
        gateway_mac: Callable[[dict[str, str]], str | None] | None = None,
    ) -> None:
        self._load_devices = load_devices
        self._load_state = load_state
        self._save_state = save_state
        self._emit = emit
        self._wait_for_network = wait_for_network
        self._sender = sender
        self._sleep = sleep
        self._clock = clock
        self._monotonic = monotonic
        self._bursts = bursts
        self._network_wait = network_wait
        self._gateway_mac = gateway_mac
        self._locks = {trigger: asyncio.Lock() for trigger in AUTO_TRIGGERS}

    # -- configuration lookups -------------------------------------------------

    def burst_for(self, trigger: str) -> tuple[float, ...]:
        if self._bursts is not None:
            return self._bursts[trigger]
        return MANUAL_BURST if trigger == "manual" else AUTO_BURST

    def network_wait_for(self, trigger: str) -> float:
        return (self._network_wait or NETWORK_WAIT)[trigger]

    def is_running(self, trigger: str) -> bool:
        lock = self._locks.get(trigger)
        return lock is not None and lock.locked()

    # -- public API ------------------------------------------------------------

    def record(
        self,
        trigger: str,
        outcome: str,
        reason: str | None,
        results: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "trigger": trigger,
            "at": int(self._clock()),
            "outcome": outcome,
            "reason": reason,
            "results": results or {},
        }

    async def dispatch(
        self,
        trigger: str,
        ids: list[str] | None = None,
        *,
        on_network: Callable[[dict[str, str]], None] | None = None,
    ) -> dict[str, Any]:
        """Run one wake and return its record (also saved to state and emitted).

        Automatic triggers run at most once at a time each: a second call while
        one is in progress returns a ``skipped`` / "Already running" record that is
        neither saved nor emitted. Manual wakes always run. ``on_network`` is called
        with the route once the network is up (the boot gate uses it).
        """
        if trigger not in TRIGGERS:
            return self.record(trigger, "failed", f"Unknown trigger '{trigger}'")
        if trigger == "manual":
            return await self._run(trigger, ids, on_network)
        lock = self._locks[trigger]
        if lock.locked():
            get_logger().info("%s wake already running; ignoring this one", trigger)
            return self.record(trigger, "skipped", ALREADY_RUNNING)
        async with lock:
            return await self._run(trigger, ids, on_network)

    async def publish(self, record: dict[str, Any]) -> None:
        """Save ``record`` as the latest (and per-trigger automation) state and emit it."""
        try:
            state = self._load_state()
            state["last"] = record
            if record["trigger"] in AUTO_TRIGGERS:
                state.setdefault("automation", {})[record["trigger"]] = record
            self._save_state(state)
        except Exception as exc:  # a full disk must not lose the event
            get_logger().error("Could not save wake state: %s", exc)
        emit = self._emit
        if emit is None:
            import decky

            emit = decky.emit
        try:
            await emit("dispatched", record)
        except Exception as exc:
            get_logger().error("Could not emit dispatched event: %s", exc)

    # -- internals -------------------------------------------------------------

    async def _network(self, trigger: str) -> dict[str, str] | None:
        timeout = self.network_wait_for(trigger)
        started = self._monotonic()
        if self._wait_for_network is not None:
            route = await self._wait_for_network(timeout)
        else:
            route = await netinfo.wait_for_network(timeout, sleep=self._sleep)
        elapsed = self._monotonic() - started
        if route is None:
            get_logger().warning("%s wake: no network after %.1fs", trigger, elapsed)
        else:
            get_logger().info(
                "%s wake: network up after %.1fs (%s via %s)",
                trigger,
                elapsed,
                route.get("iface"),
                route.get("gateway"),
            )
        return route

    def _devices(self) -> list[dict[str, Any]]:
        try:
            return self._load_devices()
        except Exception as exc:
            get_logger().error("Could not load devices: %s", exc)
            return []

    async def _run(
        self,
        trigger: str,
        ids: list[str] | None,
        on_network: Callable[[dict[str, str]], None] | None,
    ) -> dict[str, Any]:
        automatic = trigger in AUTO_TRIGGERS
        route: dict[str, str] | None = None

        if automatic:
            route = await self._network(trigger)
            if route is None:
                return await self._finish(self.record(trigger, "no_network", NO_NETWORK))
            if on_network is not None:
                on_network(route)

        devices = self._devices()
        if ids is not None:
            wanted = set(ids)
            devices = [d for d in devices if d.get("id") in wanted]
        results: dict[str, dict[str, Any]] = {}
        targets: list[dict[str, Any]] = []

        if automatic:
            devices = [d for d in devices if trigger in (d.get("auto") or [])]
            if not devices:
                return await self._finish(self.record(trigger, "skipped", NO_OPT_IN))
            # Known v1 limitation: the gateway is checked once, before the burst;
            # a network change during the (up to 20 s) burst isn't re-checked.
            router_mac = self._router_mac(trigger, route, devices)
            for device in devices:
                skip = self._home_gate(device, route, router_mac)
                if skip is not None:
                    get_logger().info("%s wake: skipping %s (%s)", trigger, device["id"], skip)
                    results[device["id"]] = {
                        "name": device.get("name", ""),
                        "status": "skipped",
                        "error": skip,
                    }
                else:
                    targets.append(device)
        else:
            if not devices:
                reason = NO_DEVICES if ids is None else NO_MATCH
                return await self._finish(self.record(trigger, "skipped", reason))
            targets = devices
            route = await self._network(trigger)
            if route is None:
                return await self._finish(self.record(trigger, "no_network", NO_NETWORK))
            if on_network is not None:
                on_network(route)

        if targets:
            results.update(await self._burst(trigger, targets))
        outcome, reason = summarise(results)
        return await self._finish(self.record(trigger, outcome, reason, results))

    def _router_mac(
        self, trigger: str, route: dict[str, str], devices: list[dict[str, Any]]
    ) -> str | None:
        """The current router's MAC, read once per wake and only when a device needs it."""
        if not any(d.get("home_gateway_mac") for d in devices):
            return None
        try:
            mac = (self._gateway_mac or netinfo.gateway_mac)(route)
        except Exception as exc:
            get_logger().error("Could not read the router's address: %s", exc)
            mac = None
        if mac is None:
            get_logger().info(
                "%s wake: router %s not in ARP yet; checking its IP only",
                trigger,
                route.get("gateway"),
            )
        else:
            get_logger().info("%s wake: router %s is %s", trigger, route.get("gateway"), mac)
        return mac

    @staticmethod
    def _home_gate(
        device: dict[str, Any], route: dict[str, str], router_mac: str | None
    ) -> str | None:
        """The skip reason for ``device`` on this network, or ``None`` to wake it."""
        gateway = device.get("home_gateway")
        if not gateway:
            return None
        if gateway != route["gateway"]:
            return NOT_HOME
        expected = device.get("home_gateway_mac")
        if expected and router_mac is not None and router_mac != expected:
            return OTHER_NETWORK
        return None

    async def _finish(self, record: dict[str, Any]) -> dict[str, Any]:
        get_logger().info(
            "%s wake: %s%s",
            record["trigger"],
            record["outcome"],
            f" ({record['reason']})" if record["reason"] else "",
        )
        await self.publish(record)
        return record

    async def _burst(
        self, trigger: str, targets: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        send = self._sender or packet.send_magic_packet
        sent: set[str] = set()
        errors: dict[str, str] = {}
        packets: dict[str, bytes] = {}
        for device in targets:
            try:
                packets[device["id"]] = packet.magic_packet(device["mac"], device.get("secureon"))
            except ValueError as exc:
                errors[device["id"]] = describe_error(exc)

        elapsed = 0.0
        for offset in self.burst_for(trigger):
            if offset > elapsed:
                await self._sleep(offset - elapsed)
                elapsed = offset
            for device in targets:
                payload = packets.get(device["id"])
                if payload is None:
                    continue
                try:
                    send(
                        payload,
                        device.get("broadcast") or "255.255.255.255",
                        device.get("port") or 9,
                    )
                except Exception as exc:  # isolate each device from the others
                    if not isinstance(exc, (OSError, ValueError)):
                        get_logger().exception("Unexpected error waking %s", device["id"])
                    errors[device["id"]] = describe_error(exc)
                else:
                    sent.add(device["id"])

        results: dict[str, dict[str, Any]] = {}
        for device in targets:
            device_id = device["id"]
            if device_id in sent:
                results[device_id] = {"name": device.get("name", ""), "status": "sent"}
            else:
                results[device_id] = {
                    "name": device.get("name", ""),
                    "status": "error",
                    "error": errors.get(device_id, ALL_FAILED),
                }
        return results
