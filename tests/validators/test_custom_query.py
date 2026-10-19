"""Custom-query validator tests."""

from __future__ import annotations

from app.core.config import (
    CustomValidationConfig,
    MappingConfig,
    MigrationConfig,
    ValidationConfig,
)
from app.core.enums import ComparisonOperator, DatabaseType, ValidationStatus
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.database import QueryResult
from app.validators.base import ValidationContext
from app.validators.custom_query import CustomQueryValidator
from tests.conftest import MockAdapter


class ScalarAdapter(MockAdapter):
    """MockAdapter whose execute_query returns a fixed scalar."""

    def __init__(self, db_type: DatabaseType, value) -> None:
        super().__init__(db_type, [])
        self._value = value

    async def execute_query(self, sql: str, parameters: dict | None = None) -> QueryResult:
        return QueryResult(columns=["v"], rows=[(self._value,)], row_count=1)


def _ctx(src, tgt, checks: list[CustomValidationConfig]) -> ValidationContext:
    config = MigrationConfig(
        migration={"name": "t"},
        source={"type": "oracle", "host": "h", "service": "s", "username": "u", "password": "p"},
        target={"type": "azure_postgresql", "host": "h", "database": "d", "username": "u", "password": "p"},
        mapping=MappingConfig(),
        validation=ValidationConfig(custom_validations=checks),
    )
    return ValidationContext(
        source_adapter=src,
        target_adapter=tgt,
        mapping=MappingResolver(config.mapping),
        config=config,
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=DatabaseCapabilities(),
    )


async def test_equal_scalars_pass() -> None:
    check = CustomValidationConfig(
        name="active users", source_query="q1", target_query="q2",
        comparison=ComparisonOperator.EQUAL,
    )
    ctx = _ctx(ScalarAdapter(DatabaseType.ORACLE, 42), ScalarAdapter(DatabaseType.AZURE_POSTGRESQL, 42), [check])
    results = await CustomQueryValidator().validate(ctx)
    assert results[0].status == ValidationStatus.PASS


async def test_unequal_scalars_fail() -> None:
    check = CustomValidationConfig(
        name="active users", source_query="q1", target_query="q2",
        comparison=ComparisonOperator.EQUAL,
    )
    ctx = _ctx(ScalarAdapter(DatabaseType.ORACLE, 42), ScalarAdapter(DatabaseType.AZURE_POSTGRESQL, 41), [check])
    results = await CustomQueryValidator().validate(ctx)
    assert results[0].status == ValidationStatus.FAIL


async def test_approximate_within_tolerance_passes() -> None:
    check = CustomValidationConfig(
        name="revenue", source_query="q1", target_query="q2",
        comparison=ComparisonOperator.APPROXIMATE, tolerance=1.0,
    )
    ctx = _ctx(ScalarAdapter(DatabaseType.ORACLE, 100.4), ScalarAdapter(DatabaseType.AZURE_POSTGRESQL, 100.0), [check])
    results = await CustomQueryValidator().validate(ctx)
    assert results[0].status == ValidationStatus.PASS


async def test_no_custom_checks_returns_empty() -> None:
    ctx = _ctx(ScalarAdapter(DatabaseType.ORACLE, 1), ScalarAdapter(DatabaseType.AZURE_POSTGRESQL, 1), [])
    assert await CustomQueryValidator().validate(ctx) == []
