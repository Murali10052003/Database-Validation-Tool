"""Schema comparison tests."""

from __future__ import annotations

import pytest

from app.comparison.schema_comparator import SchemaComparator
from app.core.config import MappingConfig
from app.core.enums import DatabaseType, LogicalType, ValidationStatus
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel


def _col(name: str, logical: LogicalType, **kw) -> ColumnModel:
    return ColumnModel(
        name=name,
        ordinal_position=kw.pop("pos", 1),
        native_type=kw.pop("native_type", "X"),
        logical_type=logical,
        **kw,
    )


def _db(db_type: DatabaseType, schema: str, table: str, columns: list[ColumnModel]) -> DatabaseModel:
    return DatabaseModel(
        database_type=db_type,
        schemas=[
            SchemaModel(
                name=schema,
                tables=[TableModel(schema_name=schema, name=table, columns=columns)],
            )
        ],
    )


def _comparator(mapping: MappingConfig | None = None) -> SchemaComparator:
    return SchemaComparator(
        mapping=MappingResolver(mapping or MappingConfig()),
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=DatabaseCapabilities(),
    )


def test_identical_schema_passes() -> None:
    src = _db(DatabaseType.ORACLE, "HR", "EMPLOYEES", [_col("ID", LogicalType.INTEGER)])
    tgt = _db(DatabaseType.AZURE_POSTGRESQL, "hr", "employees", [_col("id", LogicalType.INTEGER)])
    results = _comparator().compare(src, tgt)
    assert all(r.status != ValidationStatus.FAIL for r in results)
    assert any(r.check_id == "column:HR.EMPLOYEES.ID" and r.status == ValidationStatus.PASS for r in results)


def test_missing_target_table_fails() -> None:
    src = _db(DatabaseType.ORACLE, "HR", "EMPLOYEES", [_col("ID", LogicalType.INTEGER)])
    tgt = DatabaseModel(
        database_type=DatabaseType.AZURE_POSTGRESQL,
        schemas=[SchemaModel(name="hr")],
    )
    results = _comparator().compare(src, tgt)
    table_result = next(r for r in results if r.check_id == "table:HR.EMPLOYEES")
    assert table_result.status == ValidationStatus.FAIL


def test_type_mismatch_fails() -> None:
    src = _db(DatabaseType.ORACLE, "HR", "T", [_col("C", LogicalType.INTEGER)])
    tgt = _db(DatabaseType.AZURE_POSTGRESQL, "hr", "t", [_col("c", LogicalType.STRING)])
    results = _comparator().compare(src, tgt)
    col = next(r for r in results if r.check_id == "column:HR.T.C")
    assert col.status == ValidationStatus.FAIL
    assert any("type mismatch" in d for d in col.differences)


def test_extra_target_column_is_warning() -> None:
    src = _db(DatabaseType.ORACLE, "HR", "T", [_col("A", LogicalType.INTEGER)])
    tgt = _db(
        DatabaseType.AZURE_POSTGRESQL,
        "hr",
        "t",
        [_col("a", LogicalType.INTEGER), _col("b", LogicalType.STRING, pos=2)],
    )
    results = _comparator().compare(src, tgt)
    extra = next(r for r in results if r.check_id.startswith("column-extra"))
    assert extra.status == ValidationStatus.WARNING


def test_schema_mapping_is_applied() -> None:
    src = _db(DatabaseType.ORACLE, "HR", "EMPLOYEES", [_col("ID", LogicalType.INTEGER)])
    tgt = _db(DatabaseType.AZURE_POSTGRESQL, "public", "employees", [_col("id", LogicalType.INTEGER)])
    mapping = MappingConfig(schemas={"HR": "public"})
    results = _comparator(mapping).compare(src, tgt)
    schema_result = next(r for r in results if r.check_id == "schema:HR")
    assert schema_result.status == ValidationStatus.PASS


@pytest.mark.parametrize("precision,target_type,expected", [
    (4, LogicalType.SMALLINT, ValidationStatus.PASS),
    (5, LogicalType.SMALLINT, ValidationStatus.FAIL),
    (9, LogicalType.INTEGER, ValidationStatus.PASS),
    (10, LogicalType.INTEGER, ValidationStatus.FAIL),
    (10, LogicalType.BIGINT, ValidationStatus.PASS),
    (18, LogicalType.BIGINT, ValidationStatus.PASS),
    (19, LogicalType.BIGINT, ValidationStatus.FAIL),
    (None, LogicalType.BIGINT, ValidationStatus.FAIL),
])
def test_oracle_numeric_mapping_requires_declared_range_to_fit(precision, target_type, expected) -> None:
    source = _col("VALUE", LogicalType.DECIMAL, native_type="NUMBER", precision=precision, scale=0)
    target = _col("value", target_type, native_type=target_type.value)
    result = _comparator()._compare_column_pair(source, target, "HR.T.VALUE", "hr.t.value")
    assert result.status == expected


@pytest.mark.parametrize("source_type,target_type", [
    (LogicalType.UNKNOWN, LogicalType.UNKNOWN),
    (LogicalType.UNKNOWN, LogicalType.STRING),
    (LogicalType.STRING, LogicalType.UNKNOWN),
])
def test_unknown_types_never_pass(source_type, target_type) -> None:
    result = _comparator()._compare_column_pair(
        _col("VALUE", source_type), _col("value", target_type), "HR.T.VALUE", "hr.t.value",
    )
    assert result.status == ValidationStatus.NOT_SUPPORTED
    assert "incomplete datatype coverage" in result.message


def test_unknown_type_does_not_hide_structural_failure() -> None:
    result = _comparator()._compare_column_pair(
        _col("VALUE", LogicalType.UNKNOWN, nullable=True),
        _col("value", LogicalType.UNKNOWN, nullable=False), "HR.T.VALUE", "hr.t.value",
    )
    assert result.status == ValidationStatus.FAIL
    assert "incomplete datatype coverage" in result.message
    assert any("nullable mismatch" in diff for diff in result.differences)


@pytest.mark.parametrize("source_precision,source_scale,target_precision,target_scale", [
    (9, 0, 10, 0), (10, None, 10, 0), (3, 5, 3, 4), (2, -3, 2, 0),
])
def test_postgres_numeric_declarations_are_compared_exactly(source_precision, source_scale, target_precision, target_scale) -> None:
    comparator = SchemaComparator(MappingResolver(MappingConfig()), DatabaseType.AZURE_POSTGRESQL,
                                  DatabaseType.AZURE_POSTGRESQL, DatabaseCapabilities())
    result = comparator._compare_column_pair(
        _col("value", LogicalType.DECIMAL, precision=source_precision, scale=source_scale),
        _col("value", LogicalType.DECIMAL, precision=target_precision, scale=target_scale),
        "public.t.value", "public.t.value",
    )
    assert result.status == ValidationStatus.FAIL


def test_postgres_numeric_is_not_implicitly_equivalent_to_integer() -> None:
    comparator = SchemaComparator(MappingResolver(MappingConfig()), DatabaseType.AZURE_POSTGRESQL,
                                  DatabaseType.AZURE_POSTGRESQL, DatabaseCapabilities())
    result = comparator._compare_column_pair(
        _col("value", LogicalType.DECIMAL, precision=9, scale=0),
        _col("value", LogicalType.INTEGER), "public.t.value", "public.t.value",
    )
    assert result.status == ValidationStatus.FAIL
