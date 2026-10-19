"""Opt-in, read-only datatype certification against separately provisioned databases."""

from __future__ import annotations

import asyncio
import os
import re
import sys

import pytest

from app.core.config import MigrationConfig
from app.core.enums import ValidationProfile
from app.services.validation_service import ValidationService
from tests.integration.datatype_fixtures.cases import CASES

PATHS = {
    "oracle_postgres": "MV_DATATYPE_ORACLE_CONFIG",
    "postgres_postgres": "MV_DATATYPE_POSTGRES_CONFIG",
}


def find_result(report, prefix, table):
    matches = [result for result in report.results
               if result.check_id.casefold().startswith(prefix + ":")
               and table.casefold() in result.check_id.casefold().split(".")]
    assert matches, f"No {prefix} result for {table}; check discovery and fixture setup"
    return matches


@pytest.fixture(scope="module", params=[
    (path, scenario) for path in PATHS for scenario in ("good", "bad", "shape")
], ids=lambda pair: "-".join(pair))
def live_report(request):
    path, scenario = request.param
    config_path = os.environ.get(PATHS[path])
    if not config_path:
        pytest.skip(f"Set {PATHS[path]} after provisioning the isolated datatype fixtures")
    config = MigrationConfig.from_yaml(config_path)
    expected_source = "oracle" if path == "oracle_postgres" else "azure_postgresql"
    assert config.source.type.value == expected_source
    assert config.target.type.value == "azure_postgresql"
    source_schema = "MV_DT_SOURCE" if path == "oracle_postgres" else "mv_dt_source"
    assert config.mapping.schemas == {source_schema: "mv_dt_good"}, (
        "Use the dedicated fixture mapping; do not point this suite at application schemas"
    )
    assert not any((config.mapping.tables, config.mapping.columns,
                    config.mapping.excluded_objects, config.mapping.type_overrides))
    config.mapping.schemas = {source_schema: f"mv_dt_{scenario}"}
    config.validation.profile = ValidationProfile.FULL
    config.validation.data.chunk_size = 100
    config.validation.custom_validations = []
    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        report = loop.run_until_complete(ValidationService().validate(
            config, f"datatype-{path}-{scenario}"))
    finally:
        loop.close()
    assert report.source and report.target, "Database discovery did not complete"
    source_version = str(report.source.version)
    target_version = str(report.target.version)
    if path == "oracle_postgres":
        assert re.search(r"\b(?:19|21)(?:\.|c\b)", source_version), source_version
    else:
        assert re.search(r"PostgreSQL (?:16|17)\b", source_version), source_version
    assert re.search(r"PostgreSQL (?:16|17)\b", target_version), target_version
    errors = [result.check_id for result in report.results
              if result.status.value == "ERROR" and "." not in result.check_id]
    assert not errors, f"Execution errors (not acceptable mismatch results): {errors}"
    return report, path, scenario


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.table)
def test_live_datatypes(live_report, case, record_property):
    report, path, scenario = live_report
    if path not in case.paths:
        pytest.skip("PostgreSQL-only fixture; no Oracle mapping claimed")
    record_property("source_version", report.source.version)
    record_property("target_version", report.target.version)
    record_property("datatype_path", path)
    record_property("scenario", scenario)
    table = case.table
    counts = find_result(report, "row_count", table)
    assert all(result.status.value == "PASS" and result.source_value == 4
               and result.target_value == 4 for result in counts), table
    for result in find_result(report, "null_count", table):
        value_column = result.check_id.casefold().endswith(".value")
        expected_nulls = sum(value == "NULL" for value in case.values) + 1 if value_column else 0
        changed_null = value_column and case.null_mismatch and scenario == "bad"
        assert result.source_value == expected_nulls, (table, result.model_dump())
        assert result.target_value == expected_nulls + int(changed_null), table
        assert result.status.value == ("FAIL" if changed_null else "PASS"), table
    columns = find_result(report, "column", table)
    values = [result for result in columns if result.check_id.casefold().endswith(".value")]
    assert len(values) == 1, table
    expected = "NOT_SUPPORTED" if case.support == "unsupported" else (
        "FAIL" if scenario == "shape" else "PASS")
    assert values[0].status.value == expected, (table, values[0].model_dump())
    for prefix in ("checksum",):
        if scenario == "shape" and case.support != "unsupported":
            continue
        expected = "NOT_SUPPORTED" if case.support == "unsupported" else (
            "PASS" if scenario == "good" else "FAIL")
        results = find_result(report, prefix, table)
        assert all(result.status.value == expected for result in results), (
            table, prefix, [result.model_dump() for result in results])
    if case.aggregate and scenario != "shape":
        expected = "PASS" if scenario == "good" or case.aggregate_preserved else "FAIL"
        assert all(result.status.value == expected
                   for result in find_result(report, "aggregate", table)), table
