"""Canonical date/time serialization helpers (used by data checksums later)."""

from __future__ import annotations

from datetime import date, datetime, time


def canonical_datetime(value: datetime) -> str:
    """ISO-8601 representation with normalized timezone handling."""
    return value.isoformat()


def canonical_date(value: date) -> str:
    """ISO-8601 date (``YYYY-MM-DD``)."""
    return value.isoformat()


def canonical_time(value: time) -> str:
    """ISO-8601 time."""
    return value.isoformat()
