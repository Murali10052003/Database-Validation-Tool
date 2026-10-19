"""Row-count and connectivity validator tests."""

from __future__ import annotations

import pytest

from app.core.config import MappingConfig, MigrationConfig
from app.core.enums import DatabaseType, LogicalType, ValidationStatus
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel
from app.validators.base import ValidationContext
from app.validators.connectivity import ConnectivityValidator
from app.validators.row_count import RowCountValidator
from tests.conftest import MockAdapter


def _table(schema: str, name: str, rows: int) -> TableModel:
    return TableModel(
        schema_name=schema,
        name=name,
        row_count=rows,
        columns=[ColumnModel(name="id", ordinal_position=1, native_type="int", logical_type=LogicalType.INTEGER)],
    )


def _model(db_type: DatabaseType, schema: str, tables: list[TableModel]) -> DatabaseModel:
    return DatabaseModel(database_type=db_type, schemas=[SchemaModel(name=schema, tables=tables)])


def _ctx(source_adapter, target_adapter, source_model, target_model) -> ValidationContext:
    config = MigrationConfig(
        migration={"name": "t"},
        source={"type": "oracle", "host": "h", "service": "s", "username": "u", "password": "p"},
        target={"type": "azure_postgresql", "host": "h", "database": "d", "username": "u", "password": "p"},
        mapping=MappingConfig(schemas={"HR": "hr"}),
    )
    return ValidationContext(
        source_adapter=source_adapter,
        target_adapter=target_adapter,
        mapping=MappingResolver(config.mapping),
        config=config,
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=DatabaseCapabilities(),
        source_model=source_model,
        target_model=target_model,
    )


async def test_row_count_match_passes() -> None:
    src_tables = [_table("HR", "EMP", 100)]
    tgt_tables = [_table("hr", "emp", 100)]
    src = MockAdapter(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=src_tables)])
    tgt = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=tgt_tables)])
    ctx = _ctx(src, tgt, _model(DatabaseType.ORACLE, "HR", src_tables), _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_tables))

    results = await RowCountValidator().validate(ctx)
    assert results[0].status == ValidationStatus.PASS


async def test_row_count_mismatch_fails() -> None:
    src_tables = [_table("HR", "EMP", 100)]
    tgt_tables = [_table("hr", "emp", 90)]
    src = MockAdapter(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=src_tables)])
    tgt = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=tgt_tables)])
    ctx = _ctx(src, tgt, _model(DatabaseType.ORACLE, "HR", src_tables), _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_tables))

    results = await RowCountValidator().validate(ctx)
    assert results[0].status == ValidationStatus.FAIL


async def test_row_count_missing_target_is_skipped() -> None:
    src_tables = [_table("HR", "EMP", 100)]
    src = MockAdapter(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=src_tables)])
    tgt = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=[])])
    ctx = _ctx(src, tgt, _model(DatabaseType.ORACLE, "HR", src_tables), _model(DatabaseType.AZURE_POSTGRESQL, "hr", []))

    results = await RowCountValidator().validate(ctx)
    assert results[0].status == ValidationStatus.SKIPPED


async def test_connectivity_success() -> None:
    src = MockAdapter(DatabaseType.ORACLE, [])
    tgt = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [])
    ctx = _ctx(src, tgt, None, None)
    results = await ConnectivityValidator().validate(ctx)
    assert all(r.status == ValidationStatus.PASS for r in results)


async def test_connectivity_failure_is_error() -> None:
    src = MockAdapter(DatabaseType.ORACLE, [], connect_ok=False)
    tgt = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [])
    ctx = _ctx(src, tgt, None, None)
    results = await ConnectivityValidator().validate(ctx)
    assert any(r.status == ValidationStatus.ERROR for r in results)


async def test_prior_table_result_survives_later_validator_exception(monkeypatch):
    from app.validators.engine import ValidationEngine

    tables = [_table("HR", "FIRST", 12), _table("HR", "SECOND", 12)]
    source = MockAdapter(DatabaseType.ORACLE, [SchemaModel(name="HR", tables=tables)])
    target = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr", tables=tables)])
    ctx = _ctx(source, target, _model(DatabaseType.ORACLE, "HR", tables),
               _model(DatabaseType.AZURE_POSTGRESQL, "hr", tables))
    saved = []
    ctx.result_sink = lambda stage, result: saved.append(result.model_copy(deep=True))
    validator = RowCountValidator()
    compare = validator._compare_table

    async def fail_second(context, schema, table, lookup):
        if table == "SECOND":
            assert saved[0].source_object == "HR.FIRST"
            raise RuntimeError("Unexpected comparison failure")
        return await compare(context, schema, table, lookup)

    monkeypatch.setattr(validator, "_compare_table", fail_second)
    results = await ValidationEngine._safe_run(validator, ctx)
    assert [result.status for result in results] == [ValidationStatus.PASS, ValidationStatus.ERROR]
    assert results[0].source_value == 12


async def test_storage_error_stops_validation_without_becoming_check_error():
    from app.validators.base import ResultPersistenceError
    from app.validators.engine import ValidationEngine

    source = MockAdapter(DatabaseType.ORACLE, [])
    target = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [])
    ctx = _ctx(source, target, None, None)

    def fail_write(stage, result):
        raise OSError("Disk full")

    ctx.result_sink = fail_write
    with pytest.raises(ResultPersistenceError):
        await ValidationEngine._safe_run(ConnectivityValidator(), ctx)


def test_abrupt_process_exit_keeps_two_completed_tables(tmp_path):
    import subprocess
    import sys
    import textwrap

    from app.core.catalog import Catalog

    path = tmp_path / "abrupt.sqlite3"
    script = textwrap.dedent("""
        import asyncio
        import os
        import sys
        from app.core.catalog import Catalog
        from app.validators.engine import ValidationEngine
        from tests.validators.test_row_count import (
            _ctx, _table, _model, MockAdapter, DatabaseType, SchemaModel, RowCountValidator,
        )

        catalog = Catalog(sys.argv[1])
        run_id = 'd' * 12
        tables = [_table('HR', name, 12) for name in ['FIRST', 'SECOND', 'THIRD']]

        class InterruptedSource(MockAdapter):
            async def get_row_count(self, schema, table):
                if table == 'THIRD':
                    assert catalog.partial_report(run_id)['total'] == 2
                    os._exit(23)
                return 12

        source = InterruptedSource(DatabaseType.ORACLE, [SchemaModel(name='HR', tables=tables)])
        target = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name='hr', tables=tables)])
        ctx = _ctx(source, target, _model(DatabaseType.ORACLE, 'HR', tables),
                   _model(DatabaseType.AZURE_POSTGRESQL, 'hr', tables))
        catalog.start_run(run_id, ctx.config)
        catalog.plan_stages(run_id, ['row_count', 'null_count'])
        ctx.result_sink = lambda stage, result: catalog.record_result(run_id, stage, result)
        ctx.stage_sink = lambda stage, status: catalog.record_stage(run_id, stage, status)
        asyncio.run(ValidationEngine._safe_run(RowCountValidator(), ctx))
    """)
    process = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, timeout=30)
    assert process.returncode == 23, process.stderr
    catalog = Catalog(path)
    catalog.recover_runs()
    partial = catalog.partial_report("d" * 12)
    assert partial["state"] == "interrupted"
    assert not partial["coverage_complete"]
    assert partial["total"] == 2
    assert [result["source_object"] for result in partial["results"]] == ["HR.FIRST", "HR.SECOND"]
    assert [stage["status"] for stage in partial["stages"]] == ["interrupted", "pending"]
