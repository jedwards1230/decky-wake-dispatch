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


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[" * 100000, "nested too deeply"),
        ("[" + "1" * 5000 + "]", "number that is too long"),
        ("[" + " " * devices.IMPORT_MAX_BYTES + "]", "too large to import"),
        ('["' + "é" * (devices.IMPORT_MAX_BYTES // 2) + '"]', "too large to import"),
    ],
    ids=["deeply-nested", "huge-int", "over-cap", "over-cap-in-bytes"],
)
def test_import_rejects_unreadable_or_oversized_text(text, message) -> None:
    with pytest.raises(ConfigError) as err:
        devices.import_devices(text, "replace", [])
    assert message in str(err.value)


def _many(count: int) -> list[dict]:
    return [
        device(i % 250 + 1, id=f"pc-{i}", mac=f"aa:bb:cc:dd:{i // 256:02x}:{i % 256:02x}")
        for i in range(count)
    ]


def test_device_cap_on_save_and_import() -> None:
    assert len(devices.validate_devices(_many(devices.MAX_DEVICES))) == devices.MAX_DEVICES
    with pytest.raises(DeviceError) as err:
        devices.validate_devices(_many(devices.MAX_DEVICES + 1))
    assert err.value.message == "You can save at most 64 devices."
    with pytest.raises(ConfigError, match="65 devices; the limit is 64"):
        devices.import_devices(json.dumps(_many(65)), "replace", [])
    existing = devices.validate_devices(_many(60))
    incoming = [device(1, id=f"new-{i}", mac=f"aa:bb:cc:dd:ff:{i:02x}") for i in range(5)]
    with pytest.raises(ConfigError, match="Merging would give 65 devices"):
        devices.import_devices(json.dumps(incoming), "merge", existing)


def test_stored_devices_over_cap_keep_first_and_count_dropped() -> None:
    kept, dropped = devices.sanitise_stored(_many(70))
    assert [d["id"] for d in kept] == [f"pc-{i}" for i in range(64)]
    assert dropped == 6


@pytest.mark.parametrize("bad_id", ["pc,1", "pc 1", "x" * 129, "pc/1", "pc;1", "ü-pc", "pc​1"])
def test_bad_ids_rejected(bad_id) -> None:
    with pytest.raises(DeviceError) as err:
        devices.validate_devices([device(1, id=bad_id)])
    assert err.value.field == "id"


def test_good_ids_and_generated_ids_match_pattern() -> None:
    for good in ("pc-1", "A.b_C-9", "x" * 128):
        assert devices.validate_devices([device(1, id=good)])[0]["id"] == good
    for name in ("Gaming PC", "!!!", "Ünïcödé PC", "x" * 200):
        [d] = devices.validate_devices([device(1, id="", name=name[:64])])
        assert devices.ID_PATTERN.fullmatch(d["id"])


def test_stored_device_with_bad_id_gets_a_new_one() -> None:
    kept, dropped = devices.sanitise_stored([device(1, id="has, comma")])
    assert dropped == 1  # repaired: counts so the caller backs the file up
    assert devices.ID_PATTERN.fullmatch(kept[0]["id"]) and kept[0]["id"] != "has, comma"


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  Gaming   PC ", "Gaming PC"),
        ("Gaming‮PC", "GamingPC"),  # bidi override
        ("Gam​ing‍ PC﻿", "Gaming PC"),  # zero-width characters
        ("Tab\tand\nnewline", "Tab and newline"),
        ("Café", "Café"),  # NFC
        ("\x00\x07Bell", "Bell"),
        ("​‮", ""),
        (None, ""),
    ],
)
def test_sanitise_name(raw, clean) -> None:
    assert devices.sanitise_name(raw) == clean


def test_sanitise_name_caps_length() -> None:
    assert devices.sanitise_name("a" * 100) == "a" * devices.NAME_MAX
    assert devices.sanitise_name("ab cd", max_len=3) == "ab"


def test_names_are_sanitised_on_save() -> None:
    [d] = devices.validate_devices([device(1, name="‮Office​  PC")])
    assert d["name"] == "Office PC"
    with pytest.raises(DeviceError) as err:
        devices.validate_devices([device(1, name="​‮")])
    assert err.value.field == "name"


@pytest.mark.parametrize(
    "host",
    [
        "192.0.2.1",
        "2001:db8::1",
        "pc",
        "office-pc.example",
        "office-pc.example.",
        "a" * 63 + ".example",
        "1pc.example",
    ],
)
def test_good_hosts(host) -> None:
    assert devices.validate_devices([device(1, host=host)])[0]["host"] == host


@pytest.mark.parametrize(
    "host",
    [
        "pc example",
        "-pc.example",
        "pc-.example",
        "pc..example",
        "a" * 64 + ".example",
        ("a" * 60 + ".") * 5,
        "pc_1.example",
        "http://pc",
        "pc:22",
        "fe80::1%eth0",
        "pc​.example",
        ".",
    ],
)
def test_bad_hosts(host) -> None:
    with pytest.raises(DeviceError) as err:
        devices.validate_devices([device(1, host=host)])
    assert err.value.field == "host"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"host": "my_pc.lan", "status_port": 22}, {"host": None, "status_port": 22}),
        ({"host": "fe80::1%wlan0", "status_port": 22}, {"host": None, "status_port": 22}),
        ({"host": "caf\u00e9.local", "status_port": 22}, {"host": None, "status_port": 22}),
        ({"host": "192.0.2.5", "status_port": 0}, {"host": "192.0.2.5", "status_port": None}),
        (
            {"id": "bad id", "host": "bad host", "status_port": "22"},
            {"host": None, "status_port": None},
        ),
    ],
)
def test_stored_device_with_bad_status_fields_is_kept_without_them(overrides, expected) -> None:
    kept, repaired = devices.sanitise_stored([device(1, **overrides), device(2)])
    assert repaired == 1
    assert [d["mac"] for d in kept] == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    assert {k: kept[0][k] for k in expected} == expected


def test_stored_device_with_other_bad_field_is_still_dropped() -> None:
    kept, dropped = devices.sanitise_stored([device(1, host="bad host", mac="x"), device(2)])
    assert dropped == 1
    assert [d["id"] for d in kept] == ["pc-2"]
