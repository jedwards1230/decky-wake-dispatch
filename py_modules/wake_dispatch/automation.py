"""Automatic triggers: the boot gate and the resume watcher.

Boot: the kernel's boot_id changes on every boot. When it differs from the one
saved in state, wait for a route, save the new boot_id (only once a route was
found, so a boot without network is retried on the next plugin load of the
same boot), then dispatch "boot". Same boot_id -> nothing (plugin reloads and
Decky restarts don't re-wake).

Resume: a background loop sleeps ``tick`` seconds; if more than ``gap`` seconds
of elapsed real time (CLOCK_BOOTTIME, which keeps counting through suspend)
passed between two ticks the process was frozen in suspend, so dispatch
"resume". CLOCK_BOOTTIME ignores wall-clock steps (NTP, manual changes), so they
can't fake a resume. CLOCK_MONOTONIC can't be used to cancel it out: on some
kernels it also advances through s2idle, which would hide every suspend.

Each resume dispatch runs as its own task (so the watcher keeps its cadence);
the Dispatcher drops a resume that arrives while another is still running.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from wake_dispatch import netinfo
from wake_dispatch.dispatch import Dispatcher
from wake_dispatch.log import get_logger

RESUME_TICK = 5.0
RESUME_GAP = 20.0


def _boottime() -> float:
    """Elapsed real time (CLOCK_BOOTTIME), including time spent suspended."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


# Default clock for the resume watcher; wall time only where BOOTTIME is missing.
elapsed_clock: Callable[[], float] = _boottime if hasattr(time, "CLOCK_BOOTTIME") else time.time


class Automation:
    def __init__(
        self,
        dispatcher: Dispatcher,
        *,
        load_state: Callable[[], dict[str, Any]],
        save_state: Callable[[dict[str, Any]], None],
        read_boot_id: Callable[[], str | None] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        clock: Callable[[], float] | None = None,
        tick: float | None = None,
        gap: float | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self._load_state = load_state
        self._save_state = save_state
        self._read_boot_id = read_boot_id
        self._sleep = sleep
        self._clock = clock or elapsed_clock
        self._tick = tick
        self._gap = gap
        self.boot_task: asyncio.Task[Any] | None = None
        self.watch_task: asyncio.Task[Any] | None = None
        self._resume_tasks: set[asyncio.Task[Any]] = set()

    # -- boot ------------------------------------------------------------------

    async def run_boot(self) -> dict[str, Any] | None:
        """Dispatch "boot" if this is a new boot; returns the record or ``None``."""
        boot_id = (self._read_boot_id or netinfo.read_boot_id)()
        if boot_id is None:
            get_logger().warning("Could not read the boot id; skipping boot wake")
            return None
        try:
            saved = self._load_state().get("boot_id")
        except Exception as exc:
            get_logger().error("Could not read state: %s", exc)
            saved = None
        if saved == boot_id:
            get_logger().info("Same boot as before; no boot wake")
            return None

        def remember_boot(_route: dict[str, str]) -> None:
            try:
                state = self._load_state()
                state["boot_id"] = boot_id
                self._save_state(state)
            except Exception as exc:
                get_logger().error("Could not save the boot id: %s", exc)

        get_logger().info("New boot detected; waiting for the network")
        return await self.dispatcher.dispatch("boot", on_network=remember_boot)

    # -- resume ----------------------------------------------------------------

    def _fire_resume(self, frozen_for: float) -> asyncio.Task[Any] | None:
        if self.dispatcher.is_running("resume"):
            get_logger().info("Resume detected but a resume wake is still running; ignoring")
            return None
        get_logger().info(
            "Resume detected (%.0fs of elapsed real time between ticks); waking devices",
            frozen_for,
        )
        task = asyncio.get_running_loop().create_task(self.dispatcher.dispatch("resume"))
        self._resume_tasks.add(task)
        task.add_done_callback(self._resume_tasks.discard)
        return task

    async def watch_resume(self) -> None:
        """Run forever, firing a resume wake after every detected suspend."""
        tick = RESUME_TICK if self._tick is None else self._tick
        gap = RESUME_GAP if self._gap is None else self._gap
        previous = self._clock()
        while True:
            await self._sleep(tick)
            now = self._clock()
            if now - previous > gap:
                self._fire_resume(now - previous)
            previous = now

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        if self.boot_task is None:
            self.boot_task = loop.create_task(self._guarded(self.run_boot, "boot"))
        if self.watch_task is None:
            self.watch_task = loop.create_task(self._guarded(self.watch_resume, "resume watcher"))

    @staticmethod
    async def _guarded(run: Callable[[], Awaitable[Any]], what: str) -> Any:
        # Takes a factory, not a coroutine, so a task cancelled before it starts
        # doesn't leave a never-awaited coroutine behind.
        try:
            return await run()
        except asyncio.CancelledError:
            raise
        except Exception:
            get_logger().exception("Wake Dispatch %s task failed", what)
            return None

    async def stop(self) -> None:
        """Cancel and await every background task, swallowing the cancellations."""
        tasks = [t for t in (self.boot_task, self.watch_task, *self._resume_tasks) if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.boot_task = None
        self.watch_task = None
        self._resume_tasks.clear()
