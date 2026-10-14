"""Data value canonicalization/equality helpers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.comparison.data_comparator import canonical_scalar, numeric_equal, values_equal


def test_numeric_types_compare_equal_across_representations() -> None:
    assert values_equal(100, Decimal("100.00"))
    assert values_equal(Decimal("1.50"), 1.5)
    assert not values_equal("100", 100)


def test_distinct_numbers_not_equal() -> None:
    assert not values_equal(100, 101)
    assert not values_equal(Decimal("1.5"), Decimal("1.6"))


def test_none_and_bytes_and_dates() -> None:
    assert values_equal(None, None)
    assert not values_equal(None, 0)
    assert values_equal(b"\x01\x02", b"\x01\x02")
    assert values_equal(datetime(2020, 1, 1, 12, 0), datetime(2020, 1, 1, 12, 0))


def test_numeric_equal_handles_none_and_sums() -> None:
    assert numeric_equal(None, None)
    assert not numeric_equal(None, 0)
    assert numeric_equal(Decimal("12345"), 12345)
    assert not numeric_equal(Decimal("12345"), Decimal("12344"))


def test_canonical_scalar_normalizes_number_scale() -> None:
    assert canonical_scalar(Decimal("100.00")) == canonical_scalar(100)


def test_large_decimals_remain_exact() -> None:
    source = Decimal("12345678901234567890123456789012345678")
    target = Decimal("12345678901234567890123456789012345679")
    assert not values_equal(source, target)
    assert not numeric_equal(source, target)
    assert values_equal(source, int(source))


@pytest.mark.parametrize("source,target", [
    ("00123", "123"),
    ("1e2", "100"),
    (True, 1),
    (False, 0),
    (b"\x01\x02", "0102"),
    (datetime(2020, 1, 1), "2020-01-01T00:00:00"),
])
def test_distinct_typed_values_do_not_compare_equal(source, target) -> None:
    assert not values_equal(source, target)


def test_timezone_comparison_uses_instants() -> None:
    utc = datetime.fromisoformat("2026-01-01T10:00:00+00:00")
    same_instant = datetime.fromisoformat("2026-01-01T12:00:00+02:00")
    different_instant = datetime.fromisoformat("2026-01-01T10:00:00+02:00")
    assert values_equal(utc, same_instant)
    assert not values_equal(utc, different_instant)
    assert not values_equal(utc, utc.replace(tzinfo=None))


def test_structured_values_compare_recursively() -> None:
    assert values_equal({"a": 1, "b": [None, Decimal("2.0")]}, {"b": [None, 2], "a": 1})
    assert not values_equal([1, 2], [2, 1])
    assert not values_equal({"a": "001"}, {"a": "1"})
    assert not values_equal({"a": None}, {})


def test_special_numeric_values_have_explicit_semantics() -> None:
    assert values_equal(float("nan"), Decimal("NaN"))
    assert values_equal(float("inf"), Decimal("Infinity"))
    assert not values_equal(float("inf"), float("-inf"))
    assert values_equal(Decimal("-0.00"), 0)
    assert not numeric_equal("invalid", "invalid")


def test_unsupported_values_are_not_stringified() -> None:
    with pytest.raises(TypeError, match="Unsupported"):
        canonical_scalar(object())
