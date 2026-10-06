import asyncio
import time

import pytest
from helpers import Recorder, device

from wake_dispatch.automation import Automation
from wake_dispatch.dispatch import Dispatcher

HOME = {"iface": "wlan0", "gateway": "192.168.1.1"}


def build(rec: Recorder, *, route=HOME, boot_id="boot-b", **kwargs):
    async def wait(_timeout):
        return route

    async def no_sleep(_s):
        return None

    dispatcher = Dispatcher(
        load_devices=rec.load_devices,
        load_state=rec.load_state,
        save_state=rec.save_state,
        emit=rec.emit,
        wait_for_network=wait,
        sender=lambda *_a: None,
        sleep=no_sleep,
    )
    return Automation(
        dispatcher,
        load_state=rec.load_state,
        save_state=rec.save_state,
        read_boot_id=lambda: boot_id,
        **kwargs,
    )


async def test_same_boot_id_no_dispatch() -> None:
    rec = Recorder([device(1, auto=["boot"])])
    rec.state["boot_id"] = "boot-b"
    assert await build(rec).run_boot() is None
    assert rec.events == []


async def test_new_boot_without_route_does_not_save_boot_id() -> None:
    rec = Recorder([device(1, auto=["boot"])])
    rec.state["boot_id"] = "boot-a"
    record = await build(rec, route=None).run_boot()
    assert record["outcome"] == "no_network"
    assert rec.state["boot_id"] == "boot-a"
    assert rec.state["automation"]["boot"] == record
    assert rec.events == [("dispatched", record)]


async def test_new_boot_with_route_saves_and_dispatches() -> None:
    rec = Recorder([device(1, auto=["boot"]), device(2)])
    rec.state["boot_id"] = "boot-a"
    record = await build(rec).run_boot()
    assert record["outcome"] == "sent"
    assert list(record["results"]) == ["pc-1"]
    assert rec.state["boot_id"] == "boot-b"
    assert rec.state["automation"]["boot"] == record
    assert await build(rec).run_boot() is None  # second load in the same boot


async def test_zero_device_boot() -> None:
    rec = Recorder([])
    record = await build(rec).run_boot()
    assert (record["outcome"], record["reason"]) == ("skipped", "No devices opted in")
    assert rec.state["boot_id"] == "boot-b"


async def test_unreadable_boot_id_skips() -> None:
    rec = Recorder([device(1, auto=["boot"])])
    assert await build(rec, boot_id=None).run_boot() is None


class Stop(Exception):
    """Raised by the fake sleep to end the otherwise endless watcher loop."""


class FakeClock:
    """Wall clock driven by the fake sleep, with an optional jump to simulate suspend."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.jumps: dict[int, float] = {}
        self.ticks = 0
        self.stop_after = 10**9

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.ticks += 1
        if self.ticks > self.stop_after:
            raise Stop
        self.now += seconds + self.jumps.get(self.ticks, 0.0)
        await asyncio.sleep(0)


async def within(awaitable, seconds: float = 2):
    return await asyncio.wait_for(awaitable, seconds)


async def run_watcher(rec: Recorder, jump: float, ticks: int = 6):
    """Run the watcher for ``ticks`` fake ticks with one clock jump on tick 3."""
    clock = FakeClock()
    clock.jumps = {3: jump}
    clock.stop_after = ticks
    sleeps: list[float] = []
    real_sleep = clock.sleep

    async def recording_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await real_sleep(seconds)

    auto = build(rec, sleep=recording_sleep, clock=clock)
    with pytest.raises(Stop):
        await within(auto.watch_resume())
    await within(asyncio.gather(*auto._resume_tasks))
    return sleeps


async def test_resume_detected_on_clock_gap(caplog) -> None:
    rec = Recorder([device(1, auto=["resume"])])
    with caplog.at_level("INFO", logger="decky-test"):
        await run_watcher(rec, jump=300.0)
    resumes = [r for _, r in rec.events if r["trigger"] == "resume"]
    assert len(resumes) == 1
    assert resumes[0]["outcome"] == "sent"
    assert rec.state["automation"]["resume"] == resumes[0]
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("Resume detected (305s") for m in messages)
    assert any(m.startswith("resume wake: network up after ") for m in messages)


async def test_resume_threshold_is_strictly_greater_than_20s() -> None:
    rec = Recorder([device(1, auto=["resume"])])
    sleeps = await run_watcher(rec, jump=15.0)  # 5 s tick + 15 s = exactly 20.0
    assert rec.events == []
    assert set(sleeps) == {5.0}
    sleeps = await run_watcher(rec, jump=15.5)  # 20.5 s
    assert [r["trigger"] for _, r in rec.events] == ["resume"]
    assert set(sleeps) == {5.0}


def test_default_clock_is_boottime_not_wall_time(monkeypatch) -> None:
    from wake_dispatch import automation

    auto = build(Recorder())
    assert auto._clock is automation.elapsed_clock
    if not hasattr(time, "CLOCK_BOOTTIME"):
        pytest.skip("CLOCK_BOOTTIME not available on this platform")
    assert automation.elapsed_clock is automation._boottime
    before = automation.elapsed_clock()
    monkeypatch.setattr(automation.time, "time", lambda: 10**10)  # a big wall-clock step
    after = automation.elapsed_clock()
    assert 0 <= after - before < 5
    assert abs(after - time.clock_gettime(time.CLOCK_BOOTTIME)) < 5


async def test_resume_while_resume_running_is_dropped() -> None:
    rec = Recorder([device(1, auto=["resume"])])
    gate = asyncio.Event()
    auto = build(rec)

    async def slow_wait(_timeout):
        await gate.wait()
        return HOME

    auto.dispatcher._wait_for_network = slow_wait
    first = auto._fire_resume(60)
    await asyncio.sleep(0)
    assert auto._fire_resume(60) is None
    gate.set()
    await within(first)
    assert [r["trigger"] for _, r in rec.events] == ["resume"]


async def test_start_and_stop_cancel_tasks() -> None:
    rec = Recorder([device(1, auto=["boot"])])
    gate = asyncio.Event()
    auto = build(rec)

    async def never(_timeout):
        await gate.wait()

    auto.dispatcher._wait_for_network = never
    auto.start()
    boot, watch = auto.boot_task, auto.watch_task
    await asyncio.sleep(0)
    assert not boot.done() and not watch.done()
    await within(auto.stop())
    assert boot.cancelled() and watch.cancelled()
    assert auto.boot_task is None and auto.watch_task is None
    assert rec.state["boot_id"] is None


async def test_stop_cancels_in_flight_resume_tasks() -> None:
    rec = Recorder([device(1, auto=["resume"])])
    gate = asyncio.Event()
    auto = build(rec)

    async def never(_timeout):
        await gate.wait()

    auto.dispatcher._wait_for_network = never
    resume = auto._fire_resume(60)
    await asyncio.sleep(0)
    assert not resume.done()
    await within(auto.stop())
    assert resume.cancelled()
    assert not auto._resume_tasks
    assert rec.events == []
