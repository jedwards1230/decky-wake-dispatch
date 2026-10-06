"""Logger lookup shared by every module.

Decky's ``decky.logger`` writes to the plugin log file; it is looked up at call
time so the package also works (and tests run) without a real Decky runtime.
"""

from __future__ import annotations

import logging


def get_logger() -> logging.Logger:
    try:
        import decky

        return decky.logger
    except (ImportError, AttributeError):
        return logging.getLogger("wake_dispatch")
