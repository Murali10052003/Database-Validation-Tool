"""Data-level validators: null_count, aggregate, checksum, ref-integrity."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.core.config import MappingConfig, MigrationConfig
from app.core.enums import DatabaseType, LogicalType, ValidationStatus
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel, ConstraintType, ForeignKeyReference
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel
from app.validators.aggregate import AggregateValidator
from app.validators.checksum import ChecksumValidator, _digest
from app.validators.null_count import NullCountValidator
from app.validators.referential_integrity import ReferentialIntegrityValidator
from tests.conftest import MockAdapter

CAPS = DatabaseCapabilities(foreign_keys=True)


async def test_include_only_referential_integrity_uses_mapped_target_tables():
    source = DatabaseModel(database_type=DatabaseType.ORACLE, schemas=[SchemaModel(
        name="HR", tables=[TableModel(schema_name="HR", name=name) for name in ("EMP", "OTHER")],
    )])
    foreign_key = ConstraintModel(
        name="FK_PARENT", constraint_type=ConstraintType.FOREIGN_KEY, columns=["PARENT_ID"],
        references=ForeignKeyReference(ref_table="parent", ref_columns=["id"]),
    )
    target = DatabaseModel(database_type=DatabaseType.AZURE_POSTGRESQL, schemas=[SchemaModel(
        name="hr", tables=[
            TableModel(schema_name="hr", name=name, constraints=[foreign_key])
            for name in ("staff", "other", "target_only")
        ],
    )])
    target_adapter = DataMock(DatabaseType.AZURE_POSTGRESQL, [])
    target_adapter.count_orphans = AsyncMock(return_value=0)
    ctx = _ctx(DataMock(DatabaseType.ORACLE, []), target_adapter, source, target)
    ctx.config.mapping.included_objects = ["HR.EMP"]
    ctx.config.mapping.tables = {"HR.EMP": "hr.staff"}
    ctx.mapping = MappingResolver(ctx.config.mapping)

    results = await ReferentialIntegrityValidator().validate(ctx)

    assert len(results) == 1
    assert results[0].target_object == "hr.staff -> hr.parent"
    target_adapter.count_orphans.assert_awaited_once_with(
        "hr", "staff", ["PARENT_ID"], "hr", "parent", ["id"],
    )
    ctx.config.mapping.excluded_objects = ["HR.EMP"]
    ctx.mapping = MappingResolver(ctx.config.mapping)
    target_adapter.count_orphans.reset_mock()
    assert await ReferentialIntegrityValidator().validate(ctx) == []
    target_adapter.count_orphans.assert_not_awaited()


class DataMock(MockAdapter):
    """MockAdapter with scripted data-access responses keyed by (schema, table)."""

    def __init__(self, db_type: DatabaseType, schemas, *, nulls=None, aggs=None, rows=None,
                 orphans=None) -> None:
        super().__init__(db_type, schemas, capabilities=CAPS)
        self._nulls = nulls or {}
        self._aggs = aggs or {}
        self._rows = rows or {}
        self._orphans = orphans if orphans is not None else 0

    async def get_null_counts(self, schema, table, columns):
        data = self._nulls.get((schema, table), {})
        return {c: data.get(c, 0) for c in columns}

    async def get_numeric_aggregates(self, schema, table, column):
        return self._aggs.get((schema, table, column), {"min": None, "max": None, "sum": None, "count": 0})

    async def fetch_rows(self, schema, table, columns, order_by, limit=None):
        return list(self._rows.get((schema, table), []))

    async def count_orphans(self, child_schema, child_table, fk_columns, ref_schema, ref_table, ref_columns):
        return self._orphans


def _col(name: str, ltype: LogicalType = LogicalType.STRING) -> ColumnModel:
    return ColumnModel(name=name, ordinal_position=1, native_type="t", logical_type=ltype)


def _model(db: DatabaseType, schema: str, table: TableModel) -> DatabaseModel:
    return DatabaseModel(database_type=db, schemas=[SchemaModel(name=schema, tables=[table])])


def _ctx(src, tgt, src_model, tgt_model):
    config = MigrationConfig(
        migration={"name": "t"},
        source={"type": "oracle", "host": "h", "service": "s", "username": "u", "password": "p"},
        target={"type": "azure_postgresql", "host": "h", "database": "d", "username": "u", "password": "p"},
        mapping=MappingConfig(schemas={"HR": "hr"}),
    )
    from app.validators.base import ValidationContext

    return ValidationContext(
        source_adapter=src,
        target_adapter=tgt,
        mapping=MappingResolver(config.mapping),
        config=config,
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=CAPS,
        source_model=src_model,
        target_model=tgt_model,
    )


async def test_null_count_match_and_mismatch() -> None:
    table = TableModel(schema_name="HR", name="EMP", columns=[_col("ID"), _col("NAME")])
    src_model = _model(DatabaseType.ORACLE, "HR", table)
    tgt_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr",
                       TableModel(schema_name="hr", name="emp", columns=[_col("id"), _col("name")]))
    src = DataMock(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=[table])],
                   nulls={("HR", "EMP"): {"ID": 0, "NAME": 3}})
    tgt = DataMock(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=[])],
                   nulls={("hr", "emp"): {"id": 0, "name": 5}})
    results = await NullCountValidator().validate(_ctx(src, tgt, src_model, tgt_model))
    by_col = {r.source_object: r.status for r in results}
    assert by_col["HR.EMP.ID"] == ValidationStatus.PASS
    assert by_col["HR.EMP.NAME"] == ValidationStatus.FAIL


async def test_aggregate_numeric_column_compared() -> None:
    table = TableModel(schema_name="HR", name="EMP",
                       columns=[_col("SALARY", LogicalType.DECIMAL), _col("NAME")])
    src_model = _model(DatabaseType.ORACLE, "HR", table)
    tgt_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr",
                       TableModel(schema_name="hr", name="emp", columns=[_col("salary", LogicalType.DECIMAL)]))
    agg = {"min": 1000, "max": 9000, "sum": 50000, "count": 10}
    src = DataMock(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=[table])],
                   aggs={("HR", "EMP", "SALARY"): agg})
    tgt = DataMock(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=[])],
                   aggs={("hr", "emp", "salary"): dict(agg)})
    results = await AggregateValidator().validate(_ctx(src, tgt, src_model, tgt_model))
    assert len(results) == 1  # only the numeric column
    assert results[0].status == ValidationStatus.PASS


async def test_aggregate_skips_key_and_identity_columns() -> None:
    table = TableModel(
        schema_name="HR",
        name="ORDERS",
        columns=[
            _col("ORDER_ID", LogicalType.INTEGER),
            _col("CUSTOMER_ID", LogicalType.INTEGER),
            ColumnModel(
                name="EXTERNAL_ID",
                ordinal_position=3,
                native_type="NUMBER",
                logical_type=LogicalType.INTEGER,
                is_identity=True,
            ),
            _col("TOTAL_AMOUNT", LogicalType.DECIMAL),
        ],
        constraints=[
            ConstraintModel(
                name="PK_ORDERS",
                constraint_type=ConstraintType.PRIMARY_KEY,
                columns=["ORDER_ID"],
            ),
            ConstraintModel(
                name="FK_ORDERS_CUSTOMER",
                constraint_type=ConstraintType.FOREIGN_KEY,
                columns=["CUSTOMER_ID"],
            ),
        ],
    )
    target_table = TableModel(
        schema_name="hr",
        name="orders",
        columns=[
            _col("order_id", LogicalType.INTEGER),
            _col("customer_id", LogicalType.INTEGER),
            _col("external_id", LogicalType.INTEGER),
            _col("total_amount", LogicalType.DECIMAL),
        ],
    )
    src_model = _model(DatabaseType.ORACLE, "HR", table)
    tgt_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr", target_table)
    agg = {"min": 10, "max": 100, "sum": 250, "count": 4}
    src = DataMock(
        DatabaseType.ORACLE,
        [SchemaModel(name="HR", tables=[table])],
        aggs={("HR", "ORDERS", "TOTAL_AMOUNT"): agg},
    )
    tgt = DataMock(
        DatabaseType.AZURE_POSTGRESQL,
        [SchemaModel(name="hr", tables=[target_table])],
        aggs={("hr", "orders", "total_amount"): dict(agg)},
    )

    results = await AggregateValidator().validate(_ctx(src, tgt, src_model, tgt_model))

    assert [result.source_object for result in results] == ["HR.ORDERS.TOTAL_AMOUNT"]
    assert results[0].status == ValidationStatus.PASS


async def test_checksum_detects_cell_mismatch() -> None:
    table = TableModel(schema_name="HR", name="EMP", columns=[_col("ID"), _col("NAME")])
    src_model = _model(DatabaseType.ORACLE, "HR", table)
    tgt_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr",
                       TableModel(schema_name="hr", name="emp", columns=[_col("id"), _col("name")]))
    src = DataMock(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=[table])],
                   rows={("HR", "EMP"): [(1, "Alice"), (2, "Bob")]})
    tgt = DataMock(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=[])],
                   rows={("hr", "emp"): [(1, "Alice"), (2, "Bobby")]})
    results = await ChecksumValidator().validate(_ctx(src, tgt, src_model, tgt_model))
    assert results[0].status == ValidationStatus.FAIL


async def test_checksum_matches_identical_rows() -> None:
    table = TableModel(schema_name="HR", name="EMP", columns=[_col("ID"), _col("NAME")])
    src_model = _model(DatabaseType.ORACLE, "HR", table)
    tgt_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr",
                       TableModel(schema_name="hr", name="emp", columns=[_col("id"), _col("name")]))
    rows = [(1, "Alice"), (2, "Bob")]
    src = DataMock(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=[table])],
                   rows={("HR", "EMP"): list(rows)})
    tgt = DataMock(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=[])],
                   rows={("hr", "emp"): list(rows)})
    results = await ChecksumValidator().validate(_ctx(src, tgt, src_model, tgt_model))
    assert results[0].status == ValidationStatus.PASS


async def test_referential_integrity_flags_orphans() -> None:
    fk = ConstraintModel(
        name="emp_dept_fk", constraint_type=ConstraintType.FOREIGN_KEY, columns=["dept_id"],
        references=ForeignKeyReference(ref_schema="hr", ref_table="dept", ref_columns=["id"]),
    )
    tgt_table = TableModel(schema_name="hr", name="emp", constraints=[fk])
    tgt_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_table)
    tgt = DataMock(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=[tgt_table])],
                   orphans=4)
    results = await ReferentialIntegrityValidator().validate(_ctx(tgt, tgt, None, tgt_model))
    assert results[0].status == ValidationStatus.FAIL
    assert results[0].target_value == 4


@pytest.mark.parametrize("source,target", [
    ([("a\x1fb", "c")], [("a", "b\x1fc")]),
    ([("a\x1eb",)], [("a",), ("b",)]),
    ([(None,)], [("\x00",)]),
    ([("00123",)], [("123",)]),
    ([(True,)], [(1,)]),
    ([(b"abc",)], [("616263",)]),
    ([(Decimal("12345678901234567890123456789012345678"),)],
     [(Decimal("12345678901234567890123456789012345679"),)]),
])
def test_checksum_preserves_value_and_row_boundaries(source, target) -> None:
    assert _digest(source) != _digest(target)


def test_checksum_matches_equivalent_typed_values() -> None:
    source = [(Decimal("100.00"), datetime.fromisoformat("2026-01-01T10:00:00+00:00"),
               {"a": 1, "b": [2]})]
    target = [(100, datetime.fromisoformat("2026-01-01T12:00:00+02:00"),
               {"b": [2], "a": 1})]
    assert _digest(source) == _digest(target)


@pytest.mark.parametrize("validator", [ChecksumValidator])
@pytest.mark.parametrize("source_value,target_value,expected", [
    (object(), object(), ValidationStatus.NOT_SUPPORTED),
    ("00123", "123", ValidationStatus.FAIL),
    (Decimal("12345678901234567890123456789012345678"),
     Decimal("12345678901234567890123456789012345679"), ValidationStatus.FAIL),
    (datetime.fromisoformat("2026-01-01T10:00:00+00:00"),
     datetime.fromisoformat("2026-01-01T12:00:00+02:00"), ValidationStatus.PASS),
])
async def test_data_validation_uses_exact_values(validator, source_value, target_value, expected) -> None:
    source_table = TableModel(schema_name="HR", name="EMP", columns=[_col("VALUE")])
    target_table = TableModel(schema_name="hr", name="emp", columns=[_col("value")])
    source_model = _model(DatabaseType.ORACLE, "HR", source_table)
    target_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr", target_table)
    source = DataMock(DatabaseType.ORACLE, source_model.schemas,
                      rows={("HR", "EMP"): [(source_value,)]})
    target = DataMock(DatabaseType.AZURE_POSTGRESQL, target_model.schemas,
                      rows={("hr", "emp"): [(target_value,)]})
    results = await validator().validate(_ctx(source, target, source_model, target_model))
    assert results[0].status == expected
    if expected == ValidationStatus.NOT_SUPPORTED:
        assert "incomplete" in results[0].message


@pytest.mark.parametrize("validator", [ChecksumValidator])
@pytest.mark.parametrize("unknown_side", ["source", "target", "runtime"])
async def test_unsupported_table_does_not_abort_later_tables(validator, unknown_side) -> None:
    source_tables = [TableModel(schema_name="HR", name=name, columns=[_col("VALUE")])
                     for name in ["UNSUPPORTED", "SUPPORTED"]]
    target_tables = [TableModel(schema_name="hr", name=name, columns=[_col("value")])
                     for name in ["unsupported", "supported"]]
    if unknown_side == "source":
        source_tables[0].columns[0].logical_type = LogicalType.UNKNOWN
    elif unknown_side == "target":
        target_tables[0].columns[0].logical_type = LogicalType.UNKNOWN
    source_schemas = [SchemaModel(name="HR", tables=source_tables)]
    target_schemas = [SchemaModel(name="hr", tables=target_tables)]
    unsupported_value = object() if unknown_side == "runtime" else "identical"
    source = DataMock(DatabaseType.ORACLE, source_schemas, rows={
        ("HR", "UNSUPPORTED"): [(unsupported_value,)], ("HR", "SUPPORTED"): [("ok",)],
    })
    target = DataMock(DatabaseType.AZURE_POSTGRESQL, target_schemas, rows={
        ("hr", "unsupported"): [(unsupported_value,)], ("hr", "supported"): [("ok",)],
    })
    context = _ctx(source, target,
                   DatabaseModel(database_type=DatabaseType.ORACLE, schemas=source_schemas),
                   DatabaseModel(database_type=DatabaseType.AZURE_POSTGRESQL, schemas=target_schemas))
    results = await validator().validate(context)
    assert [result.status for result in results] == [ValidationStatus.NOT_SUPPORTED, ValidationStatus.PASS]
