"""Test harness: install a stub ``decky`` module before ``main`` is imported."""

from __future__ import annotations

import logging
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

emitted: list[tuple[str, tuple[Any, ...]]] = []


async def _emit(event: str, *args: Any) -> None:
    emitted.append((event, args))


_decky = types.ModuleType("decky")
_decky.DECKY_PLUGIN_SETTINGS_DIR = ""
_decky.DECKY_PLUGIN_RUNTIME_DIR = ""
_decky.DECKY_PLUGIN_LOG_DIR = ""
_decky.logger = logging.getLogger("decky-test")
_decky.emit = _emit
_decky.emitted = emitted
sys.modules["decky"] = _decky


@pytest.fixture(autouse=True)
def decky_env(tmp_path: Path) -> Iterator[types.ModuleType]:
    """Point the plugin dirs at a fresh tmp_path and clear the emit log."""
    dirs = {
        "DECKY_PLUGIN_SETTINGS_DIR": tmp_path / "settings",
        "DECKY_PLUGIN_RUNTIME_DIR": tmp_path / "runtime",
        "DECKY_PLUGIN_LOG_DIR": tmp_path / "logs",
    }
    for name, path in dirs.items():
        path.mkdir()
        setattr(_decky, name, str(path))
    emitted.clear()
    yield _decky
    emitted.clear()
