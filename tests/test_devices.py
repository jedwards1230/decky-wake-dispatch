import json
import re

import pytest
from helpers import device

from wake_dispatch import devices
from wake_dispatch.devices import ConfigError, DeviceError


def test_minimal_device_gets_defaults_and_id() -> None:
    [d] = devices.validate_devices([{"name": "  Gaming PC  ", "mac": "AA-BB-CC-DD-EE-01"}])
    assert re.fullmatch(r"gaming-pc-[0-9a-f]{6}", d["id"])
    assert d == {
        "id": d["id"],
        "name": "Gaming PC",
        "mac": "aa:bb:cc:dd:ee:01",
        "broadcast": "255.255.255.255",
        "port": 9,
        "host": None,
        "status_port": None,
        "secureon": None,
        "auto": [],
        "home_gateway": None,
    }


def test_full_device_normalised_and_unknown_keys_dropped() -> None:
    raw = device(
        1,
        secureon="AABBCCDDEEF0",
        auto=["resume", "boot", "resume"],
        home_gateway="192.168.1.1",
        host=" office.example ",
        status_port=22,
        port=7.0,
        colour="red",
    )
    [d] = devices.validate_devices([raw])
    assert d["secureon"] == "aa:bb:cc:dd:ee:f0"
    assert d["auto"] == ["resume", "boot"]
    assert d["host"] == "office.example"
    assert d["port"] == 7
    assert "colour" not in d
    assert d["id"] == "pc-1"


def test_blank_optionals_become_null() -> None:
    [d] = devices.validate_devices([device(1, secureon="", host="  ", home_gateway="")])
    assert (d["secureon"], d["host"], d["home_gateway"]) == (None, None, None)


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"name": ""}, "name", "Device 2: Enter a name of 1 to 64 characters."),
        ({"name": "x" * 65}, "name", "Device 2: Enter a name of 1 to 64 characters."),
        (
            {"mac": "aa:bb"},
            "mac",
            "Device 2: A MAC address has 12 hex digits (0-9, A-F); this one has 4.",
        ),
        (
            {"broadcast": "192.168.1.256"},
            "broadcast",
            "Device 2: The broadcast address must be an IPv4 address like 192.0.2.255; "
            "got '192.168.1.256'.",
        ),
        ({"port": 0}, "port", "Device 2: The wake port must be a whole number from 1 to 65535."),
        ({"port": True}, "port", None),
        ({"port": "9"}, "port", None),
        ({"status_port": 70000}, "status_port", None),
        ({"status_port": False}, "status_port", None),
        ({"secureon": "zz"}, "secureon", None),
        ({"auto": ["shutdown"]}, "auto", None),
        ({"auto": "boot"}, "auto", None),
        ({"home_gateway": "router"}, "home_gateway", None),
        ({"host": 5}, "host", None),
        ({"id": 5}, "id", None),
    ],
)
def test_validation_errors_name_field_and_index(overrides, field, message) -> None:
    with pytest.raises(DeviceError) as err:
        devices.validate_devices([device(1), device(2, **overrides)])
    assert err.value.field == field
    assert err.value.index == 1
    assert err.value.message.startswith("Device 2: ")
    if message:
        assert err.value.message == message
    assert err.value.as_result() == {
        "ok": False,
        "error": err.value.message,
        "field": field,
        "index": 1,
    }


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(DeviceError) as err:
        devices.validate_devices([device(1), device(2, id="pc-1")])
    assert (err.value.field, err.value.index) == ("id", 1)
    assert "already used by device 1" in err.value.message


def test_not_an_object() -> None:
    with pytest.raises(DeviceError) as err:
        devices.validate_devices([device(1), "nope"])
    assert err.value.index == 1


def test_generated_ids_are_unique(monkeypatch) -> None:
    tokens = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
    monkeypatch.setattr(devices.secrets, "token_hex", lambda _n: next(tokens))
    result = devices.validate_devices(
        [
            {"name": "Office PC", "mac": "aa:bb:cc:dd:ee:01"},
            {"name": "Office PC", "mac": "aa:bb:cc:dd:ee:02"},
        ]
    )
    assert [d["id"] for d in result] == ["office-pc-aaaaaa", "office-pc-bbbbbb"]


def test_slug_fallback_for_symbol_names() -> None:
    assert devices.generate_id("!!!", []).startswith("device-")


def test_sanitise_stored_drops_invalid() -> None:
    stored = [device(1), {"name": "broken", "mac": "nope"}, device(2, id="pc-1")]
    result, dropped = devices.sanitise_stored(stored)
    assert dropped == 1
    assert len(result) == 2
    assert result[0]["id"] == "pc-1"
    assert result[1]["id"] != "pc-1"


def test_sanitise_stored_is_stable_once_ids_exist() -> None:
    first, _ = devices.sanitise_stored([{"name": "Office PC", "mac": "aa:bb:cc:dd:ee:01"}])
    again, dropped = devices.sanitise_stored(first)
    assert (again, dropped) == (first, 0)


def test_sanitise_stored_tolerates_duplicate_macs() -> None:
    result, dropped = devices.sanitise_stored([device(1), device(2, mac="aa:bb:cc:dd:ee:01")])
    assert (len(result), dropped) == (2, 0)


def test_duplicate_macs_rejected_on_save() -> None:
    with pytest.raises(DeviceError) as err:
        devices.validate_devices([device(1), device(2), device(3, mac="AA-BB-CC-DD-EE-02")])
    assert (err.value.field, err.value.index) == ("mac", 2)
    assert err.value.message == (
        "Device 3: The MAC address aa:bb:cc:dd:ee:02 is already used by device 2."
    )


def test_export_import_round_trip() -> None:
    original = devices.validate_devices([device(1, auto=["boot"]), device(2)])
    text = devices.export_json(original)
    assert json.loads(text) == {"version": 1, "devices": original}
    assert text.startswith('{\n  "version": 1,')
    assert devices.import_devices(text, "replace", []) == original


def test_import_bare_list_replace() -> None:
    text = json.dumps([{"name": "Office PC", "mac": "aa:bb:cc:dd:ee:09"}])
    [d] = devices.import_devices(text, "replace", devices.validate_devices([device(1)]))
    assert d["mac"] == "aa:bb:cc:dd:ee:09"


def _merge(existing, incoming):
    return devices.import_devices(json.dumps(incoming), "merge", existing)


def test_merge_by_id_then_mac_else_append() -> None:
    existing = devices.validate_devices([device(1), device(2), device(3)])
    incoming = [
        device(1, name="Renamed by id"),
        {"id": "other", "name": "Renamed by MAC", "mac": "AA:BB:CC:DD:EE:02"},
        {"name": "Brand new", "mac": "aa:bb:cc:dd:ee:04"},
    ]
    merged = devices.import_devices(
        json.dumps({"version": 1, "devices": incoming}), "merge", existing
    )
    assert [d["name"] for d in merged] == [
        "Renamed by id",
        "Renamed by MAC",
        "Gaming PC 3",
        "Brand new",
    ]
    assert [d["id"] for d in merged[:3]] == ["pc-1", "pc-2", "pc-3"]
    assert merged[3]["id"].startswith("brand-new-")


def test_merge_id_match_wins_over_mac_match() -> None:
    # The incoming MAC is pc-2's, but the id says pc-1: pc-1 is updated, and since
    # that would leave two devices on one MAC, the import is rejected.
    existing = devices.validate_devices([device(1), device(2)])
    with pytest.raises(DeviceError) as err:
        _merge(existing, [{"id": "pc-1", "name": "X", "mac": "aa:bb:cc:dd:ee:02"}])
    assert (err.value.field, err.value.index) == ("mac", 0)
    assert err.value.message == (
        "Device 1: The MAC address aa:bb:cc:dd:ee:02 is already used by 'Gaming PC 2'."
    )
    # Without the collision the id match updates pc-1 in place (no append).
    merged = _merge(existing, [{"id": "pc-1", "name": "X", "mac": "aa:bb:cc:dd:ee:03"}])
    assert [(d["id"], d["name"], d["mac"]) for d in merged] == [
        ("pc-1", "X", "aa:bb:cc:dd:ee:03"),
        ("pc-2", "Gaming PC 2", "aa:bb:cc:dd:ee:02"),
    ]


def test_merge_two_imports_hitting_one_saved_device() -> None:
    existing = devices.validate_devices([device(1)])
    with pytest.raises(DeviceError) as err:
        _merge(
            existing,
            [
                {"id": "pc-1", "name": "A", "mac": "aa:bb:cc:dd:ee:05"},
                {"name": "B", "mac": "aa:bb:cc:dd:ee:01"},
            ],
        )
    assert (err.value.field, err.value.index) == ("mac", 1)
    assert err.value.message == (
        "Device 2: This matches the same saved device ('Gaming PC 1') as imported device 1."
    )


def test_import_rejects_shared_mac_within_import() -> None:
    incoming = [
        {"name": "A", "mac": "aa:bb:cc:dd:ee:07"},
        {"name": "B", "mac": "AA-BB-CC-DD-EE-07"},
    ]
    for mode in ("merge", "replace"):
        with pytest.raises(DeviceError) as err:
            devices.import_devices(json.dumps(incoming), mode, [])
        assert (err.value.field, err.value.index) == ("mac", 1)


def test_merge_ignores_old_clash_between_saved_devices() -> None:
    existing, _ = devices.sanitise_stored([device(1), device(2, mac="aa:bb:cc:dd:ee:01")])
    merged = _merge(existing, [{"name": "New", "mac": "aa:bb:cc:dd:ee:09"}])
    assert len(merged) == 3


@pytest.mark.parametrize(
    ("text", "mode", "message"),
    [
        ("{bad", "replace", "That isn't valid JSON (line 1, column 2)."),
        ("", "replace", "Paste or choose a config to import."),
        ('"x"', "merge", 'Expected a list of devices or an object with a "devices" list.'),
        ("[]", "append", 'Import mode must be "replace" or "merge".'),
    ],
)
def test_import_config_errors(text, mode, message) -> None:
    with pytest.raises(ConfigError) as err:
        devices.import_devices(text, mode, [])
    assert str(err.value) == message


def test_import_invalid_device_reports_import_index() -> None:
    text = json.dumps([device(1), device(2, mac="")])
    with pytest.raises(DeviceError) as err:
        devices.import_devices(text, "merge", [])
    assert (err.value.field, err.value.index) == ("mac", 1)
    assert err.value.message == "Device 2: Enter a MAC address."
