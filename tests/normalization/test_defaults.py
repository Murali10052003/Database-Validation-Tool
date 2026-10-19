"""Default-expression normalization tests."""

from __future__ import annotations

from app.normalization.defaults import normalize_default_expression


def test_sysdate_and_current_timestamp_are_equivalent() -> None:
    assert normalize_default_expression("SYSDATE") == normalize_default_expression(
        "CURRENT_TIMESTAMP"
    )


def test_getdate_matches_sysdate() -> None:
    assert normalize_default_expression("GETDATE()") == normalize_default_expression("SYSDATE")


def test_null_normalizes_to_none() -> None:
    assert normalize_default_expression("NULL") is None
    assert normalize_default_expression(None) is None


def test_string_literal_is_canonicalized() -> None:
    assert normalize_default_expression("'ACTIVE'") == normalize_default_expression("('ACTIVE')")


def test_number_literal_is_canonicalized() -> None:
    assert normalize_default_expression("0") == normalize_default_expression("+0")
