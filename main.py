"""Wake Dispatch backend entry point.

Decky Loader imports this module and calls the public coroutine methods of
``Plugin`` from the frontend (see docs/api.md for the frozen contract).

Decky's sandboxed plugin runner appends ``<plugin dir>/py_modules`` to
``sys.path`` before importing ``main``, so real logic lives in the
``wake_dispatch`` package under ``py_modules/``. Tests mirror that via the
``pythonpath`` setting in pyproject.toml.

With ``api_version`` 1 in plugin.json, Decky instantiates ``Plugin()`` and calls
bound methods. Legacy ``api_version`` 0 loaders called them with the class itself
as ``self``; state is created lazily (class attributes default to ``None``) so
both work. Plugin directories are resolved at call time, never at import.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import decky

from wake_dispatch import (
    automation,
    devices,
    dispatch,
    log,
    mac,
    netinfo,
    packet,
    storage,
)

_IMPORTED = (log, mac, packet, storage, devices, netinfo, dispatch, automation)


def _settings_dir() -> str:
    return decky.DECKY_PLUGIN_SETTINGS_DIR


def _runtime_dir() -> str:
    return decky.DECKY_PLUGIN_RUNTIME_DIR


def _load_devices() -> list[dict[str, Any]]:
    """Read, validate and (when anything changed) rewrite the stored device list.

    Rewriting keeps generated ids stable between reads and upgrades old-format
    files once. If a stored device had to be dropped, the original file is first
    copied to ``devices.json.bak-<ts>`` so nothing is silently lost. A file from a
    newer build (already backed up on read) is only rewritten when ids had to be
    assigned.
    """
    doc = storage.load_settings(_settings_dir())
    raw = doc["devices"]
    cleaned, dropped = devices.sanitise_stored(raw)
    changed = dropped > 0 or doc["migrated"] or cleaned != raw
    if doc["future"]:
        stored_ids = [d.get("id") if isinstance(d, dict) else None for d in raw]
        changed = dropped > 0 or [d["id"] for d in cleaned] != stored_ids
    if changed:
        path = storage.settings_path(_settings_dir())
        if dropped:
            storage.backup_file(path, "bak")
        try:
            storage.save_settings(_settings_dir(), cleaned)
        except OSError as exc:
            decky.logger.error("Could not rewrite the device list: %s", exc)
    return cleaned


def _load_state() -> dict[str, Any]:
    return storage.load_state(_runtime_dir())


def _save_state(state: dict[str, Any]) -> None:
    storage.save_state(_runtime_dir(), state)


async def _emit(event: str, record: dict[str, Any]) -> None:
    await decky.emit(event, record)


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {"last": state["last"], "automation": dict(state["automation"])}


def _save(device_list: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        storage.save_settings(_settings_dir(), device_list)
    except OSError as exc:
        decky.logger.error("Could not save devices: %s", exc)
        return {"ok": False, "error": f"Couldn't save the device list: {exc.strerror or exc}"}
    return {"ok": True, "devices": device_list}


def _dispatcher_for(plugin: Any) -> dispatch.Dispatcher:
    # ``plugin`` is a Plugin instance or, under Decky, the Plugin class itself.
    if plugin._dispatcher is None:
        plugin._dispatcher = dispatch.Dispatcher(
            load_devices=_load_devices,
            load_state=_load_state,
            save_state=_save_state,
            emit=_emit,
        )
    return plugin._dispatcher


def _automation_for(plugin: Any) -> automation.Automation:
    if plugin._automation is None:
        plugin._automation = automation.Automation(
            _dispatcher_for(plugin), load_state=_load_state, save_state=_save_state
        )
    return plugin._automation


class Plugin:
    _dispatcher: dispatch.Dispatcher | None = None
    _automation: automation.Automation | None = None

    async def list_devices(self) -> list[dict[str, Any]]:
        return _load_devices()

    async def save_devices(self, devices_in: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            validated = devices.validate_devices(devices_in)
        except devices.DeviceError as exc:
            return exc.as_result()
        return _save(validated)

    async def validate_mac(self, mac_in: str) -> dict[str, Any]:
        try:
            return {"ok": True, "mac": mac.normalise_mac(mac_in)}
        except mac.MacError as exc:
            return {"ok": False, "error": str(exc)}

    async def wake(self, ids: list[str] | None, trigger: str) -> dict[str, Any]:
        return await _dispatcher_for(self).dispatch(trigger, ids)

    async def status(self, ids: list[str] | None) -> dict[str, str]:
        return await netinfo.status_map(_load_devices(), ids)

    async def get_state(self) -> dict[str, Any]:
        return _public_state(_load_state())

    async def current_network(self) -> dict[str, str] | None:
        return netinfo.default_route()

    async def neighbours(self) -> list[dict[str, Any]]:
        return await netinfo.neighbours()

    async def export_config(self) -> str:
        return devices.export_json(_load_devices())

    async def import_config(self, text: str, mode: str) -> dict[str, Any]:
        try:
            imported = devices.import_devices(text, mode, _load_devices())
        except devices.ConfigError as exc:
            return {"ok": False, "error": str(exc)}
        except devices.DeviceError as exc:
            return exc.as_result()
        return _save(imported)

    async def _main(self) -> None:
        decky.logger.info("Wake Dispatch backend loaded (python %s)", sys.version.split()[0])
        decky.logger.info(
            "Wake Dispatch modules imported: %s",
            ", ".join(m.__name__.rsplit(".", 1)[-1] for m in _IMPORTED),
        )
        for directory in (_settings_dir(), _runtime_dir()):
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as exc:
                decky.logger.error("Could not create %s: %s", directory, exc)
        _automation_for(self).start()

    async def _unload(self) -> None:
        if self._automation is not None:
            await self._automation.stop()
        netinfo.shutdown_resolver()
        decky.logger.info("Wake Dispatch backend unloading")

    async def _uninstall(self) -> None:
        decky.logger.info("Wake Dispatch backend uninstalled")
