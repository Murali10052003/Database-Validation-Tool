"""Canonical string serialization helpers (used by data checksums later)."""

from __future__ import annotations

import unicodedata


def canonical_string(value: str, *, trim: bool = False) -> str:
    """Return an NFC-normalized string, optionally trimmed.

    Trimming is useful when a source pads fixed-width (``CHAR``) columns and the
    target does not.
    """
    text = unicodedata.normalize("NFC", value)
    if trim:
        text = text.rstrip()
    return text
