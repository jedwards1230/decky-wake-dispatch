"""MAC address and SecureOn password normalisation.

Both are 6 bytes written as 12 hex digits. Any of ``:``, ``-``, ``.`` or spaces
may separate the digits (or none at all); the result is lowercase and
colon-separated, e.g. ``aa:bb:cc:dd:ee:01``.
"""

from __future__ import annotations

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_SEPARATORS = frozenset(":-. ")
_HEX_LENGTH = 12


class MacError(ValueError):
    """A MAC address or SecureOn password that can't be used, with a user-facing message."""


def _normalise(value: object, label: str, empty_message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MacError(empty_message)
    digits: list[str] = []
    for char in value.strip():
        if char in _SEPARATORS:
            continue
        if char not in _HEX_DIGITS:
            raise MacError(
                f"{label} can only contain hex digits (0-9, A-F) and separators; found '{char}'."
            )
        digits.append(char.lower())
    if len(digits) != _HEX_LENGTH:
        raise MacError(
            f"{label} has {_HEX_LENGTH} hex digits (0-9, A-F); this one has {len(digits)}."
        )
    text = "".join(digits)
    return ":".join(text[i : i + 2] for i in range(0, _HEX_LENGTH, 2))


def normalise_mac(value: object) -> str:
    """Return ``value`` as ``aa:bb:cc:dd:ee:ff`` or raise ``MacError``."""
    return _normalise(value, "A MAC address", "Enter a MAC address.")


def normalise_secureon(value: object) -> str:
    """Return a SecureOn password in MAC form or raise ``MacError``."""
    return _normalise(value, "A SecureOn password", "Enter a SecureOn password.")


def to_bytes(normalised: str) -> bytes:
    """Convert a normalised (colon form) MAC or SecureOn value to 6 bytes."""
    return bytes.fromhex(normalised.replace(":", ""))
