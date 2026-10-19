"""Canonical number serialization helpers (used by data checksums in later phases)."""

from __future__ import annotations

from decimal import Decimal


def canonical_number(value: int | float | Decimal | str) -> str:
    """Return a deterministic string for a numeric value.

    Integers render without a decimal point; decimals drop insignificant trailing
    zeros so ``1.50`` and ``1.5`` serialize identically across databases.
    """
    dec = Decimal(str(value))
    normalized = dec.normalize()
    # ``normalize`` can yield exponential form (e.g. 1E+2); expand it.
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-", "-0"):
        text = "0"
    return text
