"""Device validation, id generation, and config import / export / merge.

Validation errors are raised as ``DeviceError`` carrying a plain-language
message plus the offending ``field`` and 0-based ``index`` so the UI can point
at the right input; ``DeviceError.as_result()`` gives the contract's
``{ok: false, error, field, index}`` shape.
"""

from __future__ import annotations

import ipaddress
import json
import re
import secrets
import unicodedata
from collections.abc import Iterable
from typing import Any

from wake_dispatch.log import get_logger
from wake_dispatch.mac import MacError, normalise_mac, normalise_secureon
from wake_dispatch.storage import SCHEMA_VERSION, migrate_settings

AUTO_TRIGGERS = ("boot", "resume")
DEFAULT_BROADCAST = "255.255.255.255"
DEFAULT_PORT = 9
NAME_MAX = 64
ID_MAX = 128
HOST_MAX = 253
MAX_DEVICES = 64
IMPORT_MAX_BYTES = 256 * 1024
# The panel joins ids with "," for some calls, so ids stay to a safe alphabet.
ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_HOST_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
# Unicode categories removed from names: controls (Cc) and format characters
# (Cf: bidi overrides, zero-width joiners and spaces, soft hyphen, ...).
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})
_WHITESPACE = re.compile(r"\s+")
IMPORT_MODES = ("replace", "merge")
FIELDS = (
    "id",
    "name",
    "mac",
    "broadcast",
    "port",
    "host",
    "status_port",
    "secureon",
    "auto",
    "home_gateway",
)


class DeviceError(ValueError):
    def __init__(self, message: str, field: str | None = None, index: int | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.index = index

    def as_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": False, "error": self.message}
        if self.field is not None:
            result["field"] = self.field
        if self.index is not None:
            result["index"] = self.index
        return result


class ConfigError(ValueError):
    """An import that can't be read at all (bad JSON, wrong shape, bad mode)."""


def _clean_text(value: Any) -> str:
    """NFC-normalise, drop Cc/Cf characters, collapse whitespace runs, trim."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFC", value)
    text = "".join(
        " " if ch.isspace() else ch
        for ch in text
        if ch.isspace() or unicodedata.category(ch) not in _STRIPPED_CATEGORIES
    )
    return _WHITESPACE.sub(" ", text).strip()


def sanitise_name(value: str, max_len: int = NAME_MAX) -> str:
    """Return ``value`` cleaned for display: NFC, no control/format characters
    (bidi overrides, zero-width), whitespace collapsed and trimmed, at most
    ``max_len`` characters. Empty or non-text input gives ``""``.
    """
    return _clean_text(value)[:max_len].rstrip()


def valid_host(value: str) -> bool:
    """True for an IP literal (no IPv6 scope) or an RFC 1123 hostname."""
    if "%" not in value:
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            pass
    name = value[:-1] if value.endswith(".") else value
    if not name or len(name) > HOST_MAX:
        return False
    return all(_HOST_LABEL.fullmatch(label) for label in name.split("."))


def _fail(index: int, field: str, message: str) -> DeviceError:
    return DeviceError(f"Device {index + 1}: {message}", field=field, index=index)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _ipv4(value: Any, index: int, field: str, label: str) -> str:
    if not isinstance(value, str):
        raise _fail(index, field, f"{label} must be an IPv4 address like 192.0.2.255.")
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ValueError:
        raise _fail(
            index, field, f"{label} must be an IPv4 address like 192.0.2.255; got '{value}'."
        ) from None


def _port(value: Any, index: int, field: str, label: str) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise _fail(index, field, f"{label} must be a whole number from 1 to 65535.")
    return value


def validate_device(raw: Any, index: int) -> dict[str, Any]:
    """Validate and normalise one device. ``id`` is kept as given ("" if missing).

    Unknown keys are dropped. Raises ``DeviceError``.
    """
    if not isinstance(raw, dict):
        raise DeviceError(f"Device {index + 1} is not an object.", index=index)

    device_id = raw.get("id")
    if _blank(device_id):
        device_id = ""
    elif not isinstance(device_id, str) or not ID_PATTERN.fullmatch(device_id.strip()):
        raise _fail(
            index,
            "id",
            f"The id must be 1 to {ID_MAX} letters, digits, dots, dashes or underscores.",
        )
    else:
        device_id = device_id.strip()

    name = _clean_text(raw.get("name"))
    if not 1 <= len(name) <= NAME_MAX:
        raise _fail(index, "name", f"Enter a name of 1 to {NAME_MAX} characters.")

    try:
        mac = normalise_mac(raw.get("mac"))
    except MacError as exc:
        raise _fail(index, "mac", str(exc)) from None

    broadcast = raw.get("broadcast")
    broadcast = (
        DEFAULT_BROADCAST
        if _blank(broadcast)
        else _ipv4(broadcast, index, "broadcast", "The broadcast address")
    )

    port = raw.get("port")
    port = DEFAULT_PORT if port is None else _port(port, index, "port", "The wake port")

    host = raw.get("host")
    if _blank(host):
        host = None
    elif not isinstance(host, str) or not valid_host(host.strip()):
        raise _fail(index, "host", "The status host must be an IP address or hostname.")
    else:
        host = host.strip()

    status_port = raw.get("status_port")
    if status_port is not None:
        status_port = _port(status_port, index, "status_port", "The status port")

    secureon = raw.get("secureon")
    if _blank(secureon):
        secureon = None
    else:
        try:
            secureon = normalise_secureon(secureon)
        except MacError as exc:
            raise _fail(index, "secureon", str(exc)) from None

    auto_raw = raw.get("auto")
    auto: list[str] = []
    if auto_raw is not None:
        if not isinstance(auto_raw, list):
            raise _fail(index, "auto", "Automation must be a list of 'boot' and/or 'resume'.")
        for trigger in auto_raw:
            if trigger not in AUTO_TRIGGERS:
                raise _fail(
                    index, "auto", f"Automation can only be 'boot' or 'resume'; got '{trigger}'."
                )
            if trigger not in auto:
                auto.append(trigger)

    home_gateway = raw.get("home_gateway")
    home_gateway = (
        None
        if _blank(home_gateway)
        else _ipv4(home_gateway, index, "home_gateway", "The home gateway")
    )

    return {
        "id": device_id,
        "name": name,
        "mac": mac,
        "broadcast": broadcast,
        "port": port,
        "host": host,
        "status_port": status_port,
        "secureon": secureon,
        "auto": auto,
        "home_gateway": home_gateway,
    }


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-")
    return slug or "device"


def generate_id(name: str, taken: Iterable[str]) -> str:
    """Return ``<slug of name>-<6 random hex>`` that isn't in ``taken``."""
    taken_set = set(taken)
    base = _slug(name)
    while True:
        candidate = f"{base}-{secrets.token_hex(3)}"
        if candidate not in taken_set:
            return candidate


def _check_unique_ids(devices: list[dict[str, Any]]) -> None:
    seen: dict[str, int] = {}
    for index, device in enumerate(devices):
        device_id = device["id"]
        if not device_id:
            continue
        if device_id in seen:
            raise _fail(
                index,
                "id",
                f"The id '{device_id}' is already used by device {seen[device_id] + 1}.",
            )
        seen[device_id] = index


def _check_unique_macs(devices: list[dict[str, Any]]) -> None:
    """Reject a second device with the same MAC (``index`` = the later one)."""
    seen: dict[str, int] = {}
    for index, device in enumerate(devices):
        if device["mac"] in seen:
            raise _fail(
                index,
                "mac",
                f"The MAC address {device['mac']} is already used by device "
                f"{seen[device['mac']] + 1}.",
            )
        seen[device["mac"]] = index


def _assign_ids(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    taken = {d["id"] for d in devices if d["id"]}
    for device in devices:
        if not device["id"]:
            device["id"] = generate_id(device["name"], taken)
            taken.add(device["id"])
    return devices


def _too_many() -> str:
    return f"You can save at most {MAX_DEVICES} devices."


def validate_devices(raw: Any) -> list[dict[str, Any]]:
    """Validate a whole device list, reject duplicate ids and MACs, then fill in missing ids."""
    if not isinstance(raw, list):
        raise DeviceError("Expected a list of devices.")
    if len(raw) > MAX_DEVICES:
        raise DeviceError(_too_many())
    devices = [validate_device(item, index) for index, item in enumerate(raw)]
    _check_unique_ids(devices)
    _check_unique_macs(devices)
    return _assign_ids(devices)


def sanitise_stored(raw: list[Any]) -> tuple[list[dict[str, Any]], int]:
    """Validate devices read from disk; return ``(devices, number dropped)``.

    Invalid entries are dropped (and logged) so one bad entry doesn't hide the
    rest; missing, duplicate or malformed ids get new ones. Only the first
    ``MAX_DEVICES`` valid devices are kept; the rest count as dropped. Duplicate
    MACs are tolerated here (the next save asks the user to fix them). The
    caller persists the result when it differs from ``raw`` so generated ids
    stay stable.
    """
    devices: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = 0
    for index, item in enumerate(raw):
        if len(devices) >= MAX_DEVICES:
            dropped += len(raw) - index
            get_logger().warning(
                "Ignoring %d stored device(s) over the limit of %d", len(raw) - index, MAX_DEVICES
            )
            break
        try:
            try:
                device = validate_device(item, index)
            except DeviceError as exc:
                if exc.field != "id":
                    raise
                device = validate_device({**item, "id": ""}, index)
        except DeviceError as exc:
            get_logger().warning("Ignoring stored device: %s", exc.message)
            dropped += 1
            continue
        if device["id"] in seen:
            device["id"] = ""
        seen.add(device["id"])
        devices.append(device)
    return _assign_ids(devices), dropped


def export_json(devices: list[dict[str, Any]]) -> str:
    return json.dumps({"version": SCHEMA_VERSION, "devices": devices}, indent=2)


def parse_import(text: Any) -> list[Any]:
    """Parse import text (a bare list or ``{version, devices}``) into a raw device list."""
    if not isinstance(text, str) or not text.strip():
        raise ConfigError("Paste or choose a config to import.")
    if len(text) > IMPORT_MAX_BYTES or len(text.encode("utf-8", "replace")) > IMPORT_MAX_BYTES:
        raise ConfigError(
            f"That config is too large to import (over {IMPORT_MAX_BYTES // 1024} KB)."
        )
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"That isn't valid JSON (line {exc.lineno}, column {exc.colno})."
        ) from None
    except (RecursionError, ValueError):
        # Nesting too deep for the parser, or a number too long to convert.
        raise ConfigError(
            "That config can't be read: it is nested too deeply or has a number that is too long."
        ) from None
    doc = migrate_settings(raw)
    if doc is None:
        raise ConfigError('Expected a list of devices or an object with a "devices" list.')
    return doc["devices"]


def merge_devices(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Upsert ``incoming`` into ``existing``: match by id first, then by MAC, else append.

    Matching only looks at the saved (``existing``) devices, never at earlier
    imported ones. A match keeps its position and its saved id (so state keyed
    by id stays valid); every other field comes from the incoming device.

    Raises ``DeviceError`` (``index`` = position in ``incoming``) when two
    imported devices match the same saved device, or when the result would hold
    two devices with the same MAC - e.g. an id match that moves a device onto a
    MAC another saved device already uses. Both lists must be validated.
    """
    merged = [dict(d) for d in existing]
    origin: list[int | None] = [None] * len(merged)  # incoming index that wrote each slot
    for index, device in enumerate(incoming):
        field = "id"
        target = None
        if device["id"]:
            target = next((i for i, d in enumerate(existing) if d["id"] == device["id"]), None)
        if target is None:
            field = "mac"
            target = next((i for i, d in enumerate(existing) if d["mac"] == device["mac"]), None)
        if target is None:
            merged.append(dict(device))
            origin.append(index)
            continue
        if origin[target] is not None:
            raise _fail(
                index,
                field,
                f"This matches the same saved device ('{existing[target]['name']}') "
                f"as imported device {origin[target] + 1}.",
            )
        merged[target] = {**device, "id": existing[target]["id"]}
        origin[target] = index

    owner: dict[str, int] = {}
    for slot, device in enumerate(merged):
        other = owner.get(device["mac"])
        if other is None:
            owner[device["mac"]] = slot
            continue
        if origin[slot] is None and origin[other] is None:
            continue  # an old clash between saved devices; not this import's fault
        blame = origin[slot] if origin[slot] is not None else origin[other]
        clash = merged[other] if origin[slot] is not None else device
        raise _fail(
            blame,
            "mac",
            f"The MAC address {device['mac']} is already used by '{clash['name']}'.",
        )
    return merged


def import_devices(text: Any, mode: Any, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the device list that results from importing ``text`` in ``mode``.

    Raises ``ConfigError`` (unreadable input) or ``DeviceError`` (an invalid device;
    ``index`` refers to the imported list).
    """
    if mode not in IMPORT_MODES:
        raise ConfigError('Import mode must be "replace" or "merge".')
    raw = parse_import(text)
    if len(raw) > MAX_DEVICES:
        raise ConfigError(f"That config has {len(raw)} devices; the limit is {MAX_DEVICES}.")
    incoming = [validate_device(item, index) for index, item in enumerate(raw)]
    _check_unique_ids(incoming)
    _check_unique_macs(incoming)
    if mode == "replace":
        return _assign_ids(incoming)
    merged = merge_devices(existing, incoming)
    if len(merged) > MAX_DEVICES:
        raise ConfigError(
            f"Merging would give {len(merged)} devices; the limit is {MAX_DEVICES}. "
            "Remove some devices or import with replace."
        )
    return _assign_ids(merged)
