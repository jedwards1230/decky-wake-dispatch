"""JSON files on disk: atomic writes, schema migration and corrupt-file handling.

Settings live in ``<settings dir>/devices.json`` as ``{"version": 1, "devices": [...]}``.
Runtime state lives in ``<runtime dir>/state.json`` as
``{"boot_id": str | None, "last": record | None, "automation": {"boot": ..., "resume": ...}}``.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from typing import Any

from wake_dispatch.log import get_logger

SCHEMA_VERSION = 1
SETTINGS_FILE = "devices.json"
STATE_FILE = "state.json"
AUTO_TRIGGERS = ("boot", "resume")


def atomic_write_json(path: str, data: Any) -> None:
    """Write ``data`` as pretty JSON to ``path`` without ever leaving a half-written file.

    The JSON goes to a temp file in the same directory, is flushed and fsynced,
    then moved over ``path`` with ``os.replace``. On any failure the temp file is
    removed, the previous ``path`` is left untouched and the error is re-raised.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    _fsync_dir(directory)


def _fsync_dir(directory: str) -> None:
    """Best-effort fsync of a directory so the rename itself survives a power cut."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def backup_file(path: str, label: str, clock: Callable[[], float] = time.time) -> str | None:
    """Copy ``path`` to ``<path>.<label>-<unix ts>`` (never overwriting); return the copy's name."""
    target = f"{path}.{label}-{int(clock())}"
    suffix = 1
    while os.path.exists(target):
        target = f"{path}.{label}-{int(clock())}-{suffix}"
        suffix += 1
    try:
        shutil.copy2(path, target)
    except OSError as exc:
        get_logger().error("Could not back up %s: %s", path, exc)
        return None
    get_logger().warning("Backed up %s to %s", path, target)
    return target


def quarantine(path: str, clock: Callable[[], float] = time.time) -> str | None:
    """Rename an unreadable file to ``<path>.corrupt-<unix ts>`` and return the new name."""
    target = f"{path}.corrupt-{int(clock())}"
    suffix = 1
    while os.path.exists(target):
        target = f"{path}.corrupt-{int(clock())}-{suffix}"
        suffix += 1
    try:
        os.replace(path, target)
    except OSError as exc:
        get_logger().error("Could not move aside unreadable file %s: %s", path, exc)
        return None
    get_logger().warning("Unreadable file %s moved to %s; starting empty", path, target)
    return target


def read_json(path: str, clock: Callable[[], float] = time.time) -> Any | None:
    """Return the parsed JSON at ``path``, or ``None`` if it is missing, unreadable or corrupt.

    A corrupt file (invalid JSON, not UTF-8, nested too deeply for the parser,
    or holding a number too long to convert) is quarantined, see ``quarantine``.
    A file that can't be opened (permissions, a directory in the way) is logged
    and left alone.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except OSError as exc:
        get_logger().error("Could not read %s: %s", path, exc)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, ValueError) as exc:
        get_logger().warning("Corrupt JSON in %s: %s", path, exc)
        quarantine(path, clock)
        return None


def migrate_settings(raw: Any) -> dict[str, Any] | None:
    """Bring a parsed settings document to the current schema.

    - bare list -> ``{"version": 1, "devices": list}``
    - dict without ``version`` -> version 1
    - a newer version than this build knows is read best-effort (its ``devices``
      list is used as-is); the caller keeps a backup of the file.
    Returns ``None`` if the shape is unrecognisable.
    """
    if isinstance(raw, list):
        return {"version": SCHEMA_VERSION, "devices": raw}
    if not isinstance(raw, dict):
        return None
    devices = raw.get("devices", [])
    if not isinstance(devices, list):
        return None
    version = raw.get("version", SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        version = SCHEMA_VERSION
    return {"version": version, "devices": devices}


def settings_path(settings_dir: str) -> str:
    return os.path.join(settings_dir, SETTINGS_FILE)


def state_path(runtime_dir: str) -> str:
    return os.path.join(runtime_dir, STATE_FILE)


def load_settings(settings_dir: str, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Load and migrate the settings file; missing or corrupt -> no devices.

    The result carries two extra flags for the caller: ``migrated`` (the file was
    an older shape - bare list or no version - and should be rewritten) and
    ``future`` (the file is from a newer build; a backup has been kept).
    """
    path = settings_path(settings_dir)
    raw = read_json(path, clock)
    empty = {"version": SCHEMA_VERSION, "devices": [], "migrated": False, "future": False}
    if raw is None:
        return empty
    doc = migrate_settings(raw)
    if doc is None:
        get_logger().warning("Settings file %s has an unexpected shape", path)
        quarantine(path, clock)
        return empty
    doc["migrated"] = not (isinstance(raw, dict) and "version" in raw)
    doc["future"] = doc["version"] > SCHEMA_VERSION
    if doc["future"]:
        backup = f"{path}.v{doc['version']}.bak"
        get_logger().warning(
            "Settings file is version %s (this build knows %s); reading best-effort",
            doc["version"],
            SCHEMA_VERSION,
        )
        if not os.path.exists(backup):
            try:
                shutil.copy2(path, backup)
            except OSError as exc:
                get_logger().error("Could not back up %s: %s", path, exc)
    doc["version"] = SCHEMA_VERSION
    return doc


def save_settings(settings_dir: str, devices: list[dict[str, Any]]) -> None:
    atomic_write_json(settings_path(settings_dir), {"version": SCHEMA_VERSION, "devices": devices})


def empty_state() -> dict[str, Any]:
    return {"boot_id": None, "last": None, "automation": {t: None for t in AUTO_TRIGGERS}}


def load_state(runtime_dir: str, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Load runtime state, filling in any missing keys; missing or corrupt -> empty state."""
    raw = read_json(state_path(runtime_dir), clock)
    state = empty_state()
    if not isinstance(raw, dict):
        if raw is not None:
            quarantine(state_path(runtime_dir), clock)
        return state
    if isinstance(raw.get("boot_id"), str):
        state["boot_id"] = raw["boot_id"]
    if isinstance(raw.get("last"), dict):
        state["last"] = raw["last"]
    automation = raw.get("automation")
    if isinstance(automation, dict):
        for trigger in AUTO_TRIGGERS:
            if isinstance(automation.get(trigger), dict):
                state["automation"][trigger] = automation[trigger]
    return state


def save_state(runtime_dir: str, state: dict[str, Any]) -> None:
    atomic_write_json(state_path(runtime_dir), state)
