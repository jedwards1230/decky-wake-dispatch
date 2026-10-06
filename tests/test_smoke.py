import inspect

import main

CONTRACT_CALLABLES = [
    "list_devices",
    "save_devices",
    "validate_mac",
    "wake",
    "status",
    "get_state",
    "current_network",
    "neighbours",
    "export_config",
    "import_config",
    "update_info",
    "set_update_check",
]
LIFECYCLE = ["_main", "_unload", "_uninstall"]


def test_plugin_exposes_contract_callables() -> None:
    for name in CONTRACT_CALLABLES + LIFECYCLE:
        attr = getattr(main.Plugin, name, None)
        assert attr is not None, f"Plugin.{name} is missing"
        assert inspect.iscoroutinefunction(attr), f"Plugin.{name} must be async"


async def test_list_devices_empty_settings_dir() -> None:
    assert await main.Plugin().list_devices() == []


async def test_main_logs_once(caplog) -> None:
    with caplog.at_level("INFO", logger="decky-test"):
        await main.Plugin()._main()
    assert any("Wake Dispatch backend loaded" in r.message for r in caplog.records)
