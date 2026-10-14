"""Data-level value comparison helpers.

Database drivers return the same logical value in different Python types (Oracle
returns ``decimal.Decimal`` where PostgreSQL may return ``int``; dates, bytes and
strings vary too). These helpers reduce a scalar to a canonical, comparable form so
data validators compare *values*, not driver representations.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.enums import LogicalType

NUMERIC_TYPES = frozenset(
    {
        LogicalType.SMALLINT,
        LogicalType.INTEGER,
        LogicalType.BIGINT,
        LogicalType.DECIMAL,
        LogicalType.FLOAT,
        LogicalType.DOUBLE,
    }
)


def canonical_scalar(value: object) -> object:
    """Return a typed, JSON-serializable value without lossy coercion."""
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float, Decimal)):
        return ("number", _canonical_number(value))
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ("binary", bytes(value).hex())
    if isinstance(value, datetime):
        if value.utcoffset() is not None:
            return ("timestamp_tz", value.astimezone(UTC).isoformat())
        return ("timestamp", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, time):
        return ("time", value.isoformat())
    if isinstance(value, timedelta):
        return ("duration", value.days, value.seconds, value.microseconds)
    if isinstance(value, UUID):
        return ("uuid", str(value))
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, (list, tuple)):
        return ("array", tuple(canonical_scalar(item) for item in value))
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return ("object", tuple((key, canonical_scalar(value[key])) for key in sorted(value)))
    raise TypeError(f"Unsupported value type for comparison: {type(value).__name__}")


def values_equal(a: object, b: object) -> bool:
    """True when two scalars are equal after canonicalization."""
    return canonical_scalar(a) == canonical_scalar(b)


def numeric_equal(a: object, b: object) -> bool:
    """True when two numeric aggregates are equal (``None`` == ``None``)."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    na, nb = _try_number(a), _try_number(b)
    if na is None or nb is None:
        return False
    return _canonical_number(na) == _canonical_number(nb)


def _canonical_number(value: int | float | Decimal) -> tuple:
    """Remove insignificant zeros without applying the Decimal context precision."""
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if number.is_nan():
        return ("nan",)
    if number.is_infinite():
        return ("infinity", number.is_signed())
    if number.is_zero():
        return (0, (0,), 0)
    sign, digits, exponent = number.as_tuple()
    assert isinstance(exponent, int)
    while digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    return (sign, digits, exponent)


def _try_number(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None

