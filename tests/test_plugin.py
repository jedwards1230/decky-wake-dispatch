"""End-to-end through ``main.Plugin`` with the stub decky module and fake procfs."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import HOME_ROUTE, device, write_network

import main
import wake_dispatch
from wake_dispatch import dispatch, netinfo

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(dispatch, "MANUAL_BURST", (0, 0, 0))
    monkeypatch.setattr(dispatch, "AUTO_BURST", (0,))
    monkeypatch.setattr(dispatch, "NETWORK_WAIT", {"manual": 0, "boot": 0, "resume": 0})


async def test_save_list_and_validate(decky_env) -> None:
    plugin = main.Plugin()
    saved = await plugin.save_devices([{"name": "Office PC", "mac": "AABBCCDDEE01"}])
    assert saved["ok"] is True
    assert await plugin.list_devices() == saved["devices"]
    on_disk = json.loads(Path(decky_env.DECKY_PLUGIN_SETTINGS_DIR, "devices.json").read_text())
    assert on_disk == {"version": 1, "devices": saved["devices"]}
    bad = await plugin.save_devices([device(1), device(2, port=0)])
    assert bad["ok"] is False and bad["field"] == "port" and bad["index"] == 1
    assert await plugin.list_devices() == saved["devices"]  # unchanged


async def test_validate_mac() -> None:
    plugin = main.Plugin()
    assert await plugin.validate_mac("AA-BB-CC-DD-EE-01") == {
        "ok": True,
        "mac": "aa:bb:cc:dd:ee:01",
    }
    assert await plugin.validate_mac("") == {"ok": False, "error": "Enter a MAC address."}


async def test_wake_sends_records_and_emits(decky_env, sandbox) -> None:
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    plugin = main.Plugin()
    await plugin.save_devices([device(1)])
    record = await plugin.wake(None, "manual")
    assert record["outcome"] == "sent"
    assert len(sandbox["sent"]) == 3
    assert sandbox["sent"][0]["address"] == ("192.168.1.255", 9)
    assert decky_env.emitted == [("dispatched", (record,))]
    state = await plugin.get_state()
    assert state == {"last": record, "automation": {"boot": None, "resume": None}}


async def test_wake_without_route_is_no_network(decky_env) -> None:
    plugin = main.Plugin()
    await plugin.save_devices([device(1)])
    record = await plugin.wake(["pc-1"], "manual")
    assert record["outcome"] == "no_network"
    assert decky_env.emitted == [("dispatched", (record,))]


async def test_current_network(sandbox) -> None:
    plugin = main.Plugin()
    assert await plugin.current_network() is None
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    assert await plugin.current_network() == {"iface": "wlan0", "gateway": "192.168.1.1"}


async def test_status_and_neighbours_empty() -> None:
    plugin = main.Plugin()
    await plugin.save_devices([device(1)])
    assert await plugin.status(None) == {"pc-1": "unknown"}
    assert await plugin.neighbours() == []


async def test_export_import(decky_env) -> None:
    plugin = main.Plugin()
    await plugin.save_devices([device(1), device(2)])
    text = await plugin.export_config()
    assert json.loads(text)["version"] == 1
    merged = await plugin.import_config(
        json.dumps([{"name": "New PC", "mac": "aa:bb:cc:dd:ee:02"}]), "merge"
    )
    assert merged["ok"] and [d["name"] for d in merged["devices"]] == ["Gaming PC 1", "New PC"]
    replaced = await plugin.import_config(text, "replace")
    assert replaced["devices"] == json.loads(text)["devices"]
    assert (await plugin.import_config("{", "merge"))["ok"] is False
    assert await plugin.import_config("[]", "bogus") == {
        "ok": False,
        "error": 'Import mode must be "replace" or "merge".',
    }


async def test_save_failure_is_reported(monkeypatch) -> None:
    def boom(*_a):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(main.storage, "save_settings", boom)
    result = await main.Plugin().save_devices([device(1)])
    assert result == {
        "ok": False,
        "error": "Couldn't save the device list: No space left on device",
    }


async def test_main_boot_zero_devices_missing_dirs(decky_env, sandbox, tmp_path, caplog) -> None:
    decky_env.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path / "gone" / "settings")
    decky_env.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path / "gone" / "runtime")
    (sandbox["fake"] / "boot_id").write_text("boot-1\n")
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    plugin = main.Plugin()
    with caplog.at_level("INFO", logger="decky-test"):
        await plugin._main()
        await plugin._automation.boot_task
        await plugin._unload()
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("Wake Dispatch backend loaded (python 3.") for m in messages)
    assert (
        "Wake Dispatch modules imported: "
        "log, mac, packet, storage, devices, netinfo, dispatch, automation, updates, discovery"
    ) in messages
    [(event, (record,))] = decky_env.emitted
    assert event == "dispatched"
    assert (record["trigger"], record["outcome"], record["reason"]) == (
        "boot",
        "skipped",
        "No devices opted in",
    )
    state = json.loads((tmp_path / "gone" / "runtime" / "state.json").read_text())
    assert state["boot_id"] == "boot-1"
    assert plugin._automation.watch_task is None


async def test_instance_lifecycle(decky_env, sandbox) -> None:
    """The normal path: Decky (api_version 1) instantiates Plugin and calls bound methods."""
    plugin = main.Plugin()
    await plugin._main()
    assert plugin._automation is not None and plugin._automation.watch_task is not None
    assert main.Plugin._automation is None  # state lives on the instance
    assert await plugin.list_devices() == []
    await plugin._unload()
    assert plugin._automation.watch_task is None
    assert netinfo._resolver_closed


async def test_legacy_class_as_self() -> None:
    """Legacy api_version 0 loaders pass the Plugin class itself as ``self``."""
    cls = type("LegacyPlugin", (main.Plugin,), {})
    await cls._main(cls)
    assert cls._automation.watch_task is not None
    assert await cls.list_devices(cls) == []
    await cls._unload(cls)
    assert cls._automation.watch_task is None


def _settings_file(decky_env) -> Path:
    return Path(decky_env.DECKY_PLUGIN_SETTINGS_DIR, "devices.json")


async def test_ids_for_id_less_file_are_stable_and_wakeable(decky_env, sandbox) -> None:
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    _settings_file(decky_env).write_text(
        json.dumps([{"name": "Office PC", "mac": "aa:bb:cc:dd:ee:01"}])  # old bare-list format
    )
    plugin = main.Plugin()
    first = await plugin.list_devices()
    second = await plugin.list_devices()
    assert first == second
    device_id = first[0]["id"]
    assert json.loads(_settings_file(decky_env).read_text()) == {"version": 1, "devices": first}
    record = await plugin.wake([device_id], "manual")
    assert list(record["results"]) == [device_id]
    assert record["outcome"] == "sent"
    assert await plugin.status([device_id]) == {device_id: "unknown"}


async def test_dropped_stored_device_is_backed_up(decky_env) -> None:
    original = json.dumps({"version": 1, "devices": [device(1), {"name": "Broken", "mac": "x"}]})
    _settings_file(decky_env).write_text(original)
    devices_now = await main.Plugin().list_devices()
    assert [d["id"] for d in devices_now] == ["pc-1"]
    settings_dir = Path(decky_env.DECKY_PLUGIN_SETTINGS_DIR)
    [backup] = list(settings_dir.glob("devices.json.bak-*"))
    assert backup.read_text() == original
    assert json.loads(_settings_file(decky_env).read_text())["devices"] == devices_now
    await main.Plugin().list_devices()
    assert len(list(settings_dir.glob("devices.json.bak-*"))) == 1  # only once


async def test_clean_file_is_not_rewritten(decky_env, monkeypatch) -> None:
    plugin = main.Plugin()
    await plugin.save_devices([device(1)])
    writes = []
    monkeypatch.setattr(main.storage, "save_settings", lambda *a: writes.append(a))
    await plugin.list_devices()
    await plugin.export_config()
    assert writes == []


async def test_future_version_file_not_rewritten_when_ids_present(decky_env) -> None:
    original = json.dumps({"version": 9, "devices": [{**device(1), "new_field": 1}]})
    _settings_file(decky_env).write_text(original)
    assert [d["id"] for d in await main.Plugin().list_devices()] == ["pc-1"]
    assert _settings_file(decky_env).read_text() == original


def test_python_version_guard() -> None:
    """Decky's runner is CPython 3.11 (CI pins it); fail fast on anything else."""
    assert sys.version_info[:2] == (3, 11)


def test_every_module_imports_under_plain_python() -> None:
    """Mirror Decky's import: py_modules on sys.path, a stub decky, then main."""
    code = (
        "import sys, types; sys.path[:0] = ['py_modules', '.']; "
        "d = types.ModuleType('decky'); import logging; d.logger = logging.getLogger('x'); "
        "sys.modules['decky'] = d; import importlib, main, wake_dispatch; "
        "[importlib.import_module('wake_dispatch.' + m) for m in wake_dispatch.MODULES]; "
        "print('ok')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "ok"
    assert len(wake_dispatch.MODULES) == 10


async def test_unload_never_yields(decky_env, sandbox, monkeypatch) -> None:
    """Decky 3.2's listener can starve the loop at shutdown: _unload must not yield."""
    monkeypatch.setattr(dispatch, "NETWORK_WAIT", {"manual": 60, "boot": 60, "resume": 60})
    (sandbox["fake"] / "boot_id").write_text("boot-1\n")
    plugin = main.Plugin()
    await plugin._main()  # boot task waits for a route that never comes; watcher sleeps
    auto = plugin._automation
    resume = auto._fire_resume(60)
    await asyncio.sleep(0)
    tasks = [auto.boot_task, auto.watch_task, resume]
    assert not any(t.done() for t in tasks)
    coro = plugin._unload()
    with pytest.raises(StopIteration):
        coro.send(None)  # ran to completion without suspending once
    assert auto.boot_task is None and auto.watch_task is None and not auto._resume_tasks
    await asyncio.gather(*tasks, return_exceptions=True)
    assert all(t.cancelled() for t in tasks)
    assert netinfo._resolver_closed


async def test_unload_without_main_never_yields() -> None:
    coro = main.Plugin()._unload()
    with pytest.raises(StopIteration):
        coro.send(None)


async def test_callables_ignore_stray_args(decky_env, sandbox) -> None:
    plugin = main.Plugin()
    await plugin.save_devices([device(1)])
    assert [d["id"] for d in await plugin.list_devices(None)] == ["pc-1"]
    assert (await plugin.get_state(None, 1))["last"] is None
    assert await plugin.current_network("x") is None
    assert await plugin.neighbours(None) == []
    assert json.loads(await plugin.export_config(None))["devices"][0]["id"] == "pc-1"
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    record = await plugin.wake(["pc-1"], "manual", "extra")
    assert record["outcome"] == "sent" and "ok" not in record
    assert (await plugin.wake())["trigger"] == "manual"  # defaults: all devices, manual
    assert await plugin.status() == {"pc-1": "unknown"}
    assert await plugin.status(["pc-1"], "extra") == {"pc-1": "unknown"}


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("pc-1", "manual"), "Device ids must be a list"),
        (([1, 2], "manual"), "Device ids must be a list"),
        (({"id": "pc-1"}, "manual"), "Device ids must be a list"),
        ((None, "shutdown"), "Unknown trigger 'shutdown'"),
        ((None, 5), "Unknown trigger 5"),
    ],
)
async def test_wake_bad_args_return_error_shape(decky_env, sandbox, args, message) -> None:
    write_network(sandbox["fake"], HOME_ROUTE, {"wlan0": "up"})
    plugin = main.Plugin()
    await plugin.save_devices([device(1)])
    result = await plugin.wake(*args)
    assert result["ok"] is False and result["error"].startswith(message)
    assert result["outcome"] == "failed" and result["results"] == {}
    assert result["trigger"] == "manual"
    assert sandbox["sent"] == [] and decky_env.emitted == []
    assert (await plugin.get_state())["last"] is None  # not recorded


@pytest.mark.parametrize("ids", ["pc-1", [1], {"pc-1": True}, 7])
async def test_status_bad_ids_return_empty(decky_env, ids) -> None:
    plugin = main.Plugin()
    await plugin.save_devices([device(1, host="192.0.2.1", status_port=22)])
    assert await plugin.status(ids) == {}


async def test_dropped_device_backed_up_once_when_rewrite_keeps_failing(
    decky_env, monkeypatch
) -> None:
    _settings_file(decky_env).write_text(
        json.dumps({"version": 1, "devices": [device(1), {"name": "Broken", "mac": "x"}]})
    )

    def boom(*_a):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(main.storage, "save_settings", boom)
    for _ in range(3):
        assert [d["id"] for d in await main.Plugin().list_devices()] == ["pc-1"]
    settings_dir = Path(decky_env.DECKY_PLUGIN_SETTINGS_DIR)
    assert len(list(settings_dir.glob("devices.json.bak-*"))) == 1


async def test_stored_device_with_bad_host_is_kept_and_backed_up_once(decky_env) -> None:
    original = json.dumps({"version": 1, "devices": [device(1, host="my_pc.lan", status_port=22)]})
    _settings_file(decky_env).write_text(original)
    for _ in range(2):
        [kept] = await main.Plugin().list_devices()
        assert (kept["id"], kept["host"], kept["status_port"]) == ("pc-1", None, 22)
    [backup] = list(Path(decky_env.DECKY_PLUGIN_SETTINGS_DIR).glob("devices.json.bak-*"))
    assert backup.read_text() == original
    assert json.loads(_settings_file(decky_env).read_text())["devices"] == [kept]


async def test_main_after_unload_reopens_the_resolver(decky_env, sandbox) -> None:
    plugin = main.Plugin()
    await plugin._main()
    await plugin._unload()
    assert await netinfo.reverse_lookup("192.0.2.8", 1.0, lambda ip: ("pc", [], [ip])) is None
    await plugin._main()
    assert await netinfo.reverse_lookup("192.0.2.8", 1.0, lambda ip: ("pc", [], [ip])) == "pc"
    await plugin._unload()
