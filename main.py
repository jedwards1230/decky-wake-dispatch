"""Wake Dispatch backend entry point.

Decky Loader imports this module and calls the public coroutine methods of
``Plugin`` from the frontend (see docs/api.md for the frozen contract).

Decky's sandboxed plugin runner appends ``<plugin dir>/py_modules`` to
``sys.path`` before importing ``main``, so real logic lives in the
``wake_dispatch`` package under ``py_modules/``. Tests mirror that via the
``pythonpath`` setting in pyproject.toml.
"""

from __future__ import annotations

import sys
from typing import Any

import decky

NOT_IMPLEMENTED = "not implemented"


def _not_implemented() -> dict[str, Any]:
    return {"ok": False, "error": NOT_IMPLEMENTED}


def _empty_record(trigger: str) -> dict[str, Any]:
    return {
        "trigger": trigger,
        "at": 0,
        "outcome": "failed",
        "reason": NOT_IMPLEMENTED,
        "results": {},
    }


class Plugin:
    async def list_devices(self) -> list[dict[str, Any]]:
        return []

    async def save_devices(self, devices: list[dict[str, Any]]) -> dict[str, Any]:
        return _not_implemented()

    async def validate_mac(self, mac: str) -> dict[str, Any]:
        return _not_implemented()

    async def wake(self, ids: list[str] | None, trigger: str) -> dict[str, Any]:
        return _empty_record(trigger)

    async def status(self, ids: list[str] | None) -> dict[str, str]:
        return {}

    async def get_state(self) -> dict[str, Any]:
        return {"last": None, "automation": {"boot": None, "resume": None}}

    async def current_network(self) -> dict[str, str] | None:
        return None

    async def neighbours(self) -> list[dict[str, Any]]:
        return []

    async def export_config(self) -> str:
        return '{\n  "version": 1,\n  "devices": []\n}'

    async def import_config(self, text: str, mode: str) -> dict[str, Any]:
        return _not_implemented()

    async def _main(self) -> None:
        decky.logger.info("Wake Dispatch backend loaded (python %s)", sys.version.split()[0])

    async def _unload(self) -> None:
        decky.logger.info("Wake Dispatch backend unloading")

    async def _uninstall(self) -> None:
        decky.logger.info("Wake Dispatch backend uninstalled")
