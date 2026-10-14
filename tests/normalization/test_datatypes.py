"""Type normalization tests."""

from __future__ import annotations

import pytest

from app.core.enums import DatabaseType, LogicalType
from app.normalization.datatypes import TypeNormalizer


@pytest.mark.parametrize("precision,scale", [(4, 0), (9, 0), (10, 0), (19, 0), (38, 0), (3, 5), (2, -3), (None, None)])
def test_oracle_number_preserves_declared_precision_and_scale(precision, scale) -> None:
    normalizer = TypeNormalizer.for_database(DatabaseType.ORACLE)
    result = normalizer.normalize("NUMBER", precision=precision, scale=scale)
    assert result.logical_type == LogicalType.DECIMAL
    assert result.precision == precision
    assert result.scale == scale


def test_oracle_decimal_with_scale_stays_decimal() -> None:
    normalizer = TypeNormalizer.for_database(DatabaseType.ORACLE)
    result = normalizer.normalize("NUMBER", precision=10, scale=2)
    assert result.logical_type == LogicalType.DECIMAL


def test_oracle_number_maps_to_postgres_numeric_signature() -> None:
    """NUMBER and NUMERIC preserve the same exact declared numeric range."""
    oracle = TypeNormalizer.for_database(DatabaseType.ORACLE)
    postgres = TypeNormalizer.for_database(DatabaseType.AZURE_POSTGRESQL)
    src = oracle.normalize("NUMBER", precision=10, scale=0)
    tgt = postgres.normalize("numeric", precision=10, scale=0)
    assert src.signature() == tgt.signature()


def test_postgres_numeric_precision_is_not_collapsed() -> None:
    normalizer = TypeNormalizer.for_database(DatabaseType.AZURE_POSTGRESQL)
    assert normalizer.normalize("numeric", precision=9, scale=0) != normalizer.normalize("numeric", precision=10, scale=0)
    assert normalizer.normalize("numeric", precision=9, scale=0) != normalizer.normalize("integer")


def test_varchar2_maps_to_string() -> None:
    oracle = TypeNormalizer.for_database(DatabaseType.ORACLE)
    result = oracle.normalize("VARCHAR2", length=100)
    assert result.logical_type in (LogicalType.STRING, LogicalType.TEXT)
