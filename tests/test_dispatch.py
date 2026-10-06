import asyncio
import errno
import socket

import pytest
from helpers import Recorder, device

from wake_dispatch import dispatch
from wake_dispatch.dispatch import Dispatcher

HOME = {"iface": "wlan0", "gateway": "192.168.1.1"}


def make(recorder: Recorder, *, route=HOME, sender=None, sleeps=None, **kwargs) -> Dispatcher:
    sent: list[tuple[bytes, str, int]] = []

    async def wait(_timeout):
        return route

    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    d = Dispatcher(
        load_devices=recorder.load_devices,
        load_state=recorder.load_state,
        save_state=recorder.save_state,
        emit=recorder.emit,
        wait_for_network=wait,
        sender=sender or (lambda data, host, port: sent.append((data, host, port))),
        sleep=sleep,
        clock=lambda: 1700000000.9,
        **kwargs,
    )
    d.sent = sent
    return d


async def test_manual_burst_and_record() -> None:
    rec = Recorder([device(1), device(2, auto=["boot"], home_gateway="192.0.2.1")])
    sleeps: list[float] = []
    d = make(rec, sleeps=sleeps)
    record = await d.dispatch("manual", None)
    assert record == {
        "trigger": "manual",
        "at": 1700000000,
        "outcome": "sent",
        "reason": None,
        "results": {
            "pc-1": {"name": "Gaming PC 1", "status": "sent"},
            "pc-2": {"name": "Gaming PC 2", "status": "sent"},
        },
    }
    assert sleeps == [1, 1]  # offsets 0, 1, 2
    assert len(d.sent) == 6
    assert all(len(data) == 102 and host == "192.168.1.255" for data, host, _ in d.sent)
    assert rec.events == [("dispatched", record)]
    assert rec.state["last"] == record
    assert rec.state["automation"] == {"boot": None, "resume": None}


async def test_manual_ids_filter_and_unknown_ids() -> None:
    rec = Recorder([device(1), device(2)])
    d = make(rec)
    record = await d.dispatch("manual", ["pc-2", "missing"])
    assert list(record["results"]) == ["pc-2"]
    none = await d.dispatch("manual", ["missing"])
    assert (none["outcome"], none["reason"]) == ("skipped", dispatch.NO_MATCH)


async def test_manual_no_devices() -> None:
    record = await make(Recorder()).dispatch("manual", None)
    assert (record["outcome"], record["reason"]) == ("skipped", "No devices configured")


async def test_manual_no_network() -> None:
    rec = Recorder([device(1)])
    record = await make(rec, route=None).dispatch("manual", None)
    assert (record["outcome"], record["reason"]) == ("no_network", "No network connection")
    assert rec.events == [("dispatched", record)]


async def test_auto_burst_offsets() -> None:
    sleeps: list[float] = []
    d = make(Recorder([device(1, auto=["resume"])]), sleeps=sleeps)
    record = await d.dispatch("resume")
    assert record["outcome"] == "sent"
    assert sleeps == [2, 3, 5, 10]
    assert len(d.sent) == 5


async def test_gateway_gating() -> None:
    rec = Recorder(
        [
            device(1, auto=["boot"], home_gateway="192.168.1.1"),
            device(2, auto=["boot"], home_gateway="198.51.100.1"),
            device(3, auto=["boot"], home_gateway=None),
            device(4, auto=["resume"]),
        ]
    )
    record = await make(rec).dispatch("boot")
    assert record["results"] == {
        "pc-1": {"name": "Gaming PC 1", "status": "sent"},
        "pc-2": {"name": "Gaming PC 2", "status": "skipped", "error": "Not on home network"},
        "pc-3": {"name": "Gaming PC 3", "status": "sent"},
    }
    assert record["outcome"] == "partial"
    assert rec.state["automation"]["boot"] == record
    assert rec.state["last"] == record


async def test_all_mismatched_gateways_skipped() -> None:
    rec = Recorder([device(1, auto=["resume"], home_gateway="198.51.100.1")])
    d = make(rec)
    record = await d.dispatch("resume")
    assert (record["outcome"], record["reason"]) == ("skipped", "Not on home network")
    assert d.sent == []


async def test_manual_ignores_gateway_and_opt_in() -> None:
    d = make(Recorder([device(1, home_gateway="198.51.100.1")]))
    assert (await d.dispatch("manual", None))["outcome"] == "sent"


async def test_auto_no_devices_opted_in() -> None:
    rec = Recorder([device(1)])
    record = await make(rec).dispatch("boot")
    assert (record["outcome"], record["reason"]) == ("skipped", "No devices opted in")
    assert rec.events == [("dispatched", record)]


async def test_auto_no_network_recorded_and_emitted() -> None:
    rec = Recorder([device(1, auto=["resume"])])
    record = await make(rec, route=None).dispatch("resume")
    assert record["outcome"] == "no_network"
    assert rec.state["automation"]["resume"] == record
    assert rec.events == [("dispatched", record)]


async def test_one_failing_device_does_not_block_others() -> None:
    sent = []

    def sender(data, host, port):
        if host == "192.0.2.255":
            raise OSError(errno.ENETUNREACH, "Network is unreachable")
        if host == "198.51.100.255":
            raise ValueError("bad")
        sent.append(host)

    rec = Recorder(
        [
            device(1, broadcast="192.0.2.255"),
            device(2),
            device(3, broadcast="198.51.100.255"),
        ]
    )
    record = await make(rec, sender=sender).dispatch("manual", None)
    assert record["results"]["pc-1"] == {
        "name": "Gaming PC 1",
        "status": "error",
        "error": "Couldn't reach the network",
    }
    assert record["results"]["pc-2"]["status"] == "sent"
    assert record["results"]["pc-3"]["status"] == "error"
    assert record["outcome"] == "partial"
    assert sent == ["192.168.1.255"] * 3


async def test_all_failed() -> None:
    def sender(*_args):
        raise PermissionError(errno.EACCES, "Permission denied")

    record = await make(Recorder([device(1), device(2)]), sender=sender).dispatch("manual", None)
    assert (record["outcome"], record["reason"]) == ("failed", "Broadcast not permitted")


async def test_later_burst_success_counts_as_sent() -> None:
    calls = []

    def sender(*_args):
        calls.append(1)
        if len(calls) == 1:
            raise OSError(errno.ENETUNREACH, "unreachable")

    record = await make(Recorder([device(1)]), sender=sender).dispatch("manual", None)
    assert record["outcome"] == "sent"


async def test_bad_stored_mac_isolated() -> None:
    record = await make(Recorder([device(1, mac="nope"), device(2)])).dispatch("manual", None)
    assert record["results"]["pc-1"]["status"] == "error"
    assert record["results"]["pc-2"]["status"] == "sent"


async def test_secureon_packet_length() -> None:
    d = make(Recorder([device(1, secureon="aa:bb:cc:dd:ee:f0")]))
    await d.dispatch("manual", None)
    assert {len(data) for data, _, _ in d.sent} == {108}


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (OSError(errno.ENETUNREACH, "x"), "Couldn't reach the network"),
        (OSError(errno.EHOSTUNREACH, "x"), "Couldn't reach the broadcast address"),
        (
            OSError(errno.EADDRNOTAVAIL, "x"),
            "The broadcast address isn't available on this network",
        ),
        (PermissionError(errno.EPERM, "x"), "Broadcast not permitted"),
        (socket.gaierror(-2, "Name or service not known"), "Address lookup failed"),
        (OSError(errno.EIO, "I/O error"), "Couldn't send the wake packet: I/O error"),
        (ValueError("odd"), "Invalid device settings: odd"),
    ],
)
def test_describe_error(exc, message) -> None:
    assert dispatch.describe_error(exc) == message


@pytest.mark.parametrize(
    ("statuses", "outcome", "reason"),
    [
        (["sent", "sent"], "sent", None),
        (["sent", "error"], "partial", "Some devices couldn't be woken"),
        (["sent", "error", "skipped"], "partial", "Some devices couldn't be woken"),
        (["sent", "skipped"], "partial", "Some devices weren't on their home network"),
        (["error", "error"], "failed", "e"),
        (["error", "skipped"], "failed", "Couldn't wake any device"),
        (["skipped", "skipped"], "skipped", "Not on home network"),
    ],
)
def test_summarise(statuses, outcome, reason) -> None:
    results = {
        str(i): {
            "name": "x",
            "status": s,
            "error": "Not on home network" if s == "skipped" else "e",
        }
        for i, s in enumerate(statuses)
    }
    assert dispatch.summarise(results) == (outcome, reason)


async def within(awaitable, seconds: float = 2):
    """Await with a deadline so a broken overlap guard fails instead of hanging."""
    return await asyncio.wait_for(awaitable, seconds)


async def test_overlapping_auto_dispatch_is_dropped_manual_still_runs() -> None:
    gate = asyncio.Event()
    rec = Recorder([device(1, auto=["resume", "boot"])])

    async def gated_wait(timeout):
        if timeout != dispatch.NETWORK_WAIT["manual"]:  # only automatic wakes block
            await gate.wait()
        return HOME

    d = make(rec)
    d._wait_for_network = gated_wait
    first = asyncio.create_task(d.dispatch("resume"))
    await asyncio.sleep(0)
    assert d.is_running("resume")
    second = await within(d.dispatch("resume"))
    assert (second["outcome"], second["reason"]) == ("skipped", "Already running")
    boot = asyncio.create_task(d.dispatch("boot"))  # the other trigger may overlap
    await asyncio.sleep(0)
    assert d.is_running("boot")

    # A manual wake on the SAME dispatcher runs while both automatic locks are held.
    manual = await within(d.dispatch("manual", None))
    assert manual["outcome"] == "sent"
    assert d.is_running("resume") and d.is_running("boot")

    gate.set()
    assert (await within(first))["outcome"] == "sent"
    assert (await within(boot))["outcome"] == "sent"
    assert not d.is_running("resume")
    triggers = [r["trigger"] for _, r in rec.events]
    assert sorted(triggers) == ["boot", "manual", "resume"]  # the dropped one isn't emitted


async def test_manual_wakes_never_block_each_other() -> None:
    gate = asyncio.Event()
    rec = Recorder([device(1)])

    async def slow_wait(_timeout):
        await gate.wait()
        return HOME

    d = make(rec)
    d._wait_for_network = slow_wait
    tasks = [asyncio.create_task(d.dispatch("manual", None)) for _ in range(2)]
    await asyncio.sleep(0)
    gate.set()
    assert [(await within(t))["outcome"] for t in tasks] == ["sent", "sent"]


async def test_partial_reasons() -> None:
    rec = Recorder(
        [
            device(1, auto=["boot"]),
            device(2, auto=["boot"], home_gateway="198.51.100.1"),
        ]
    )
    record = await make(rec).dispatch("boot")
    assert (record["outcome"], record["reason"]) == (
        "partial",
        "Some devices weren't on their home network",
    )

    def sender(_data, host, _port):
        if host == "192.0.2.255":
            raise OSError(errno.ENETUNREACH, "unreachable")

    rec = Recorder([device(1), device(2, broadcast="192.0.2.255")])
    record = await make(rec, sender=sender).dispatch("manual", None)
    assert (record["outcome"], record["reason"]) == ("partial", "Some devices couldn't be woken")


async def test_unknown_trigger() -> None:
    record = await make(Recorder()).dispatch("later")
    assert record["outcome"] == "failed"


async def test_state_save_failure_still_emits() -> None:
    rec = Recorder([device(1)])

    def broken(_state):
        raise OSError(28, "No space left on device")

    d = make(rec)
    d._save_state = broken
    record = await d.dispatch("manual", None)
    assert rec.events == [("dispatched", record)]


async def test_network_wait_values() -> None:
    seen = []
    rec = Recorder([device(1, auto=["boot", "resume"])])

    async def wait(timeout):
        seen.append(timeout)
        return HOME

    d = make(rec)
    d._wait_for_network = wait
    for trigger in ("manual", "boot", "resume"):
        await d.dispatch(trigger, None)
    assert seen == [5, 60, 20]
