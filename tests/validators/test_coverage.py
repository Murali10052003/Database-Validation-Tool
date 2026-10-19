from unittest.mock import AsyncMock

import pytest

from app.core.enums import DatabaseType, LogicalType, ValidationProfile
from app.mapping.mapping_resolver import MappingResolver
from app.models.result import CheckCoverage, ValidationResult
from app.models.table import TableModel
from app.reporting.report_builder import RunCoverage
from app.services.validation_service import ValidationService
from app.validators.checksum import ChecksumValidator
from app.validators.engine import ValidationEngine
from tests.validators.test_data_validators import DataMock, _col, _ctx, _model


async def test_include_only_full_run_queries_selected_tables_and_records_scope(monkeypatch):
    source_table = TableModel(schema_name="HR", name="T", columns=[_col("VALUE", LogicalType.INTEGER)])
    target_table = TableModel(schema_name="hr", name="t", columns=[_col("value", LogicalType.INTEGER)])
    source_model = _model(DatabaseType.ORACLE, "HR", source_table)
    target_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr", target_table)
    source_model.schemas[0].tables.append(TableModel(
        schema_name="HR", name="UNSELECTED_" * 10,
        columns=[_col("OTHER", LogicalType.INTEGER)],
    ))
    source = DataMock(DatabaseType.ORACLE, source_model.schemas)
    target = DataMock(DatabaseType.AZURE_POSTGRESQL, target_model.schemas)
    ctx = _ctx(source, target, source_model, target_model)
    ctx.config.mapping.included_objects = ["HR.T"]
    ctx.config.validation.profile = ValidationProfile.FULL
    ctx.mapping = MappingResolver(ctx.config.mapping)
    for adapter in (source, target):
        for method in ("get_row_count", "get_null_counts", "get_numeric_aggregates", "fetch_rows"):
            monkeypatch.setattr(adapter, method, AsyncMock(wraps=getattr(adapter, method)))

    async def discover(engine, context, **kwargs):
        context.source_model = source_model
        context.target_model = target_model

    monkeypatch.setattr(ValidationEngine, "_discover", discover)
    monkeypatch.setattr(
        "app.services.validation_service.adapter_factory.create",
        lambda config: source if config.type == DatabaseType.ORACLE else target,
    )
    report = await ValidationService().validate(ctx.config, "include-only-test")

    assert report.coverage.included_objects == ["HR.T"]
    assert not report.coverage.not_reached_stages
    assert all(result.status.value == "SKIPPED" for result in report.results
               if "UNSELECTED_" in (result.source_object or ""))
    for adapter, schema_name, table_name in ((source, "HR", "T"), (target, "hr", "t")):
        for method in ("get_row_count", "get_null_counts", "get_numeric_aggregates", "fetch_rows"):
            calls = getattr(adapter, method).await_args_list
            assert calls, method
            assert all(call.args[:2] == (schema_name, table_name) for call in calls), method
    assert len(source_model.schemas[0].tables) == 2


@pytest.mark.parametrize("selected_checks", [["row_count"], ["row_count", "null_count"]])
async def test_selected_checks_control_execution_discovery_and_coverage(monkeypatch, selected_checks):
    source_model = _model(DatabaseType.ORACLE, "HR", TableModel(schema_name="HR", name="T"))
    target_model = _model(DatabaseType.AZURE_POSTGRESQL, "hr", TableModel(schema_name="hr", name="t"))
    source = DataMock(DatabaseType.ORACLE, source_model.schemas)
    target = DataMock(DatabaseType.AZURE_POSTGRESQL, target_model.schemas)
    ctx = _ctx(source, target, source_model, target_model)
    ctx.config.validation.profile = ValidationProfile.QUICK
    ctx.config.validation.selected_checks = selected_checks
    discovery_options = {}

    async def discover(engine, context, **kwargs):
        discovery_options.update(kwargs)
        context.source_model = source_model
        context.target_model = target_model

    monkeypatch.setattr(ValidationEngine, "_discover", discover)
    monkeypatch.setattr(
        "app.services.validation_service.adapter_factory.create",
        lambda config: source if config.type == DatabaseType.ORACLE else target,
    )
    service = ValidationService()
    skipped = AsyncMock()
    monkeypatch.setattr(service._engine._registry["checksum"], "validate", skipped)
    report = await service.validate(ctx.config, "selected-checks-test")

    assert report.coverage.selected_stages == ["connectivity", "discovery", *selected_checks]
    assert report.coverage.reached_stages == report.coverage.selected_stages
    assert not report.coverage.not_reached_stages
    assert "checksum" in report.coverage.not_selected_stages
    skipped.assert_not_awaited()
    assert discovery_options["include_columns"] == ("null_count" in selected_checks)
    assert not discovery_options["include_structural"]
    assert any(result.category == "ROW_COUNT" for result in report.results)


def test_old_result_has_no_invented_coverage():
    result = ValidationResult(check_id="old", category="SAMPLE_DATA", status="PASS")
    assert result.coverage is None
    coverage = CheckCoverage(mode="sample", limit=10)
    assert coverage.rows_compared is None
    assert not coverage.snapshot_consistent


def test_run_coverage_preserves_legacy_sample_limit_only_when_present():
    current = RunCoverage(checksum_limit=100_000)
    assert current.sample_limit is None
    historical = RunCoverage.model_validate({"checksum_limit": 100_000, "sample_limit": 1_000})
    assert historical.sample_limit == 1_000


async def test_measured_rows_and_columns():
    source = TableModel(schema_name="HR", name="T", columns=[_col("ID", LogicalType.INTEGER)])
    target = TableModel(schema_name="hr", name="t", columns=[_col("id", LogicalType.INTEGER)])
    ctx = _ctx(DataMock(DatabaseType.ORACLE, [], rows={("HR", "T"): [(1,), (2,)]}),
               DataMock(DatabaseType.AZURE_POSTGRESQL, [], rows={("hr", "t"): [(1,), (2,)]}),
               _model(DatabaseType.ORACLE, "HR", source), _model(DatabaseType.AZURE_POSTGRESQL, "hr", target))
    result = (await ChecksumValidator().validate(ctx))[0]
    assert result.status.value == "PASS"
    assert result.coverage.source_rows_fetched == 2
    assert result.coverage.target_rows_fetched == 2
    assert result.coverage.source_columns == ["ID"]
    assert result.coverage.target_order == ["id"]
    assert not result.coverage.snapshot_consistent
    assert result.coverage.source_rows_hashed == 2
    assert result.coverage.target_rows_hashed == 2
    assert result.coverage.checksum_format == "migration-validator:typed-json:v1"


async def test_checksum_cap_hashes_both_sides_instead_of_skipping():
    source = TableModel(schema_name="HR", name="T", columns=[_col("ID", LogicalType.INTEGER)])
    target = TableModel(schema_name="hr", name="t", columns=[_col("id", LogicalType.INTEGER)])
    ctx = _ctx(DataMock(DatabaseType.ORACLE, [], rows={("HR", "T"): [(1,), (2,), (3,)]}),
               DataMock(DatabaseType.AZURE_POSTGRESQL, [], rows={("hr", "t"): [(1,), (2,), (99,)]}),
               _model(DatabaseType.ORACLE, "HR", source), _model(DatabaseType.AZURE_POSTGRESQL, "hr", target))
    ctx.config.validation.data.chunk_size = 2
    result = (await ChecksumValidator().validate(ctx))[0]
    assert result.status.value == "PASS"
    assert result.coverage.capped
    assert result.coverage.source_rows_fetched == 3
    assert result.coverage.target_rows_fetched == 3
    assert result.coverage.source_rows_hashed == 2
    assert result.coverage.target_rows_hashed == 2
    assert result.source_value == result.target_value
    assert not result.coverage.source_complete
    assert not result.coverage.target_complete
    assert "beyond the cap" in result.validation_scope
    assert result.message == "Matches within first 2-row cap; remaining rows not checked"


@pytest.mark.parametrize(("source_count", "target_count", "changed_row", "status"), [
    (0, 0, None, "PASS"),
    (99, 99, None, "PASS"),
    (100, 100, None, "PASS"),
    (101, 101, None, "PASS"),
    (101, 101, 100, "FAIL"),
    (101, 101, 101, "PASS"),
    (100, 101, None, "PASS"),
    (101, 100, None, "PASS"),
    (99, 101, None, "FAIL"),
])
async def test_checksum_first_100_rows_boundaries(source_count, target_count, changed_row, status):
    source = TableModel(schema_name="HR", name="T", columns=[_col("ID", LogicalType.INTEGER)])
    target = TableModel(schema_name="hr", name="t", columns=[_col("id", LogicalType.INTEGER)])
    source_rows = [(i,) for i in range(1, source_count + 1)]
    target_rows = [(i,) for i in range(1, target_count + 1)]
    if changed_row:
        target_rows[changed_row - 1] = (-1,)
    src = DataMock(DatabaseType.ORACLE, [])
    tgt = DataMock(DatabaseType.AZURE_POSTGRESQL, [])
    src.fetch_rows = AsyncMock(return_value=source_rows)
    tgt.fetch_rows = AsyncMock(return_value=target_rows)
    ctx = _ctx(src, tgt, _model(DatabaseType.ORACLE, "HR", source),
               _model(DatabaseType.AZURE_POSTGRESQL, "hr", target))
    result, = await ChecksumValidator().validate(ctx)
    assert result.status.value == status
    assert result.coverage.source_rows_hashed == min(source_count, 100)
    assert result.coverage.target_rows_hashed == min(target_count, 100)
    assert result.coverage.capped == (source_count > 100 or target_count > 100)
    if result.coverage.capped:
        assert "first 100-row cap; remaining rows not checked" in result.message
        if status == "FAIL":
            assert "first 100-row cap; remaining rows not checked" in result.differences[0]
    src.fetch_rows.assert_awaited_once_with("HR", "T", ["ID"], ["ID"], 101)
    tgt.fetch_rows.assert_awaited_once_with("hr", "t", ["id"], ["id"], 101)


async def test_checksum_prefix_uses_mapped_primary_key_order():
    from app.core.config import MappingConfig
    from app.models.constraint import ConstraintModel, ConstraintType

    source = TableModel(
        schema_name="HR", name="T",
        columns=[_col("VALUE", LogicalType.INTEGER), _col("ID", LogicalType.INTEGER)],
        constraints=[ConstraintModel(
            name="PK", constraint_type=ConstraintType.PRIMARY_KEY, columns=["ID"],
        )],
    )
    target = TableModel(schema_name="hr", name="t", columns=[
        _col("value", LogicalType.INTEGER), _col("target_id", LogicalType.INTEGER),
    ])
    src = DataMock(DatabaseType.ORACLE, [])
    tgt = DataMock(DatabaseType.AZURE_POSTGRESQL, [])
    src.fetch_rows = AsyncMock(return_value=[(7, i) for i in range(101)])
    tgt.fetch_rows = AsyncMock(return_value=[(7, i) for i in range(101)])
    ctx = _ctx(src, tgt, _model(DatabaseType.ORACLE, "HR", source),
               _model(DatabaseType.AZURE_POSTGRESQL, "hr", target))
    ctx.mapping = MappingResolver(MappingConfig(
        schemas={"HR": "hr"}, columns={"HR.T.ID": "target_id"},
    ))
    result, = await ChecksumValidator().validate(ctx)
    assert result.status.value == "PASS"
    src.fetch_rows.assert_awaited_once_with("HR", "T", ["VALUE", "ID"], ["ID"], 101)
    tgt.fetch_rows.assert_awaited_once_with("hr", "t", ["value", "target_id"], ["target_id"], 101)
    assert result.coverage.source_rows_hashed == 100
    assert result.coverage.target_order == ["target_id"]


@pytest.mark.parametrize("limit", [0, -1])
def test_checksum_cap_must_be_positive(limit):
    from pydantic import ValidationError

    from app.core.config import DataValidationConfig

    with pytest.raises(ValidationError):
        DataValidationConfig(chunk_size=limit)