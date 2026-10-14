import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.comparison.data_comparator import values_equal
from app.core.config import MigrationConfig
from app.core.enums import ValidationProfile
from app.validators.checksum import _digest
from tests.integration.datatype_fixtures.cases import CASES
from tests.integration.datatype_fixtures.generate import artifacts, postgres_schema
from tests.integration.test_end_to_end import find_result
from tests.integration.test_end_to_end import test_live_datatypes as check_live_case


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.table)
def test_case_contract(case):
    assert re.fullmatch(r"dt_[a-z_]+", case.table)
    assert len(case.values) == 3
    assert case.oracle_values is None or len(case.oracle_values) == 3
    assert case.changed != case.values[2] or case.aggregate_preserved
    assert case.support in {"candidate", "unsupported"}
    assert "postgres_postgres" in case.paths
    sql = postgres_schema("mv_dt_bad", "postgres_postgres", "bad")
    assert f"CREATE TABLE {case.table} " in sql
    assert "(4,NULL)" in sql
    shape = postgres_schema("mv_dt_shape", "postgres_postgres", "shape")
    assert (f"ALTER TABLE {case.table} " in shape) == (case.support != "unsupported")


def test_generator_is_deterministic_and_scoped():
    assert len({case.table for case in CASES}) == len(CASES)
    files = artifacts()
    assert files == artifacts()
    assert len(files) == 5
    for name, content in files.items():
        if not name.endswith(".sql"):
            continue
        assert "DROP " not in content.upper()
        assert "TRUNCATE " not in content.upper()
        assert "CREATE USER " not in content.upper()
        if name != "oracle-source.sql":
            assert content.startswith("BEGIN;")
            assert content.endswith("COMMIT;\n")
        else:
            assert "SESSION_USER') <> 'MV_DT_SOURCE'" in content


def test_checked_in_sql_matches_generator():
    directory = Path(__file__).parents[2] / "Queries" / "datatype-coverage"
    for name, expected in artifacts().items():
        assert (directory / name).read_text(encoding="utf-8") == expected, name


@pytest.mark.parametrize("source,equivalent,different", [
    (-9223372036854775808, Decimal("-9223372036854775808"), -9223372036854775807),
    (Decimal("99999999999999999999999999999.123456789"),
     Decimal("99999999999999999999999999999.1234567890"),
     Decimal("99999999999999999999999999999.123456788")),
    (Decimal("-0.000000001"), Decimal("-0.0000000010"), Decimal("0.000000001")),
    (1.5, Decimal("1.5"), 1.25),
    (float("nan"), float("nan"), 0),
    (float("inf"), float("inf"), float("-inf")),
    ("caf\u00e9 \u4f60\u597d \U0001f600", "caf\u00e9 \u4f60\u597d \U0001f600", "cafe"),
    (" padded ", " padded ", "padded"),
    ("", "", None),
    ("x" * 10000, "x" * 10000, "x" * 9999 + "y"),
    (b"\x00\xff" * 5000, bytearray(b"\x00\xff" * 5000), b"\x00\xfe" * 5000),
    (date(2000, 2, 29), date(2000, 2, 29), date(2000, 2, 28)),
    (datetime(2024, 11, 3, 5, 30, tzinfo=UTC),
     datetime(2024, 11, 3, 1, 30, tzinfo=timezone(timedelta(hours=-4))),
     datetime(2024, 11, 3, 1, 30, tzinfo=timezone(timedelta(hours=-5)))),
    (datetime(2024, 1, 1, microsecond=123456), datetime(2024, 1, 1, microsecond=123456),
     datetime(2024, 1, 1, microsecond=123455)),
    (time(12, 34, 56, 123456), time(12, 34, 56, 123456), time(12, 34, 56, 123455)),
    (timedelta(days=1, seconds=2), timedelta(seconds=86402), timedelta(seconds=86403)),
    (True, True, 1),
    (UUID(int=1), UUID(int=1), UUID(int=2)),
    ({"a": 1, "b": [True, None]}, {"b": [True, None], "a": 1}, {"a": 2, "b": [True, None]}),
], ids=["bigint", "precision38", "tiny_decimal", "finite_float", "nan", "infinity",
    "unicode", "whitespace", "empty", "large_text", "large_binary", "leap_date",
    "dst_offsets", "timestamp_precision", "time_precision", "interval", "boolean",
    "uuid", "json_order"])
def test_scalar_and_checksum_positive_and_mismatch(source, equivalent, different):
    assert values_equal(source, equivalent)
    assert not values_equal(source, different)
    assert _digest([(1, source)]) == _digest([(1, equivalent)])
    assert _digest([(1, source)]) != _digest([(1, different)])


def test_swapped_values_preserve_aggregates_but_not_row_values():
    case = next(case for case in CASES if case.aggregate_preserved)
    source = [int(value) for value in case.values]
    target = [source[2], source[1], source[0]]
    assert source != target
    assert (sum(source), min(source), max(source), len(source)) == (
        sum(target), min(target), max(target), len(target))


@pytest.mark.parametrize("name", ["datatype-oracle-postgres.yaml", "datatype-postgres-postgres.yaml"])
def test_example_configuration(name, monkeypatch):
    path = Path(__file__).parents[2] / "config" / "examples" / name
    for variable in re.findall(r"\$\{([A-Z_]+)\}", path.read_text()):
        monkeypatch.setenv(variable, "fixture-placeholder")
    config = MigrationConfig.from_yaml(path)
    assert config.validation.profile == ValidationProfile.FULL
    assert config.validation.data.chunk_size == 100
    assert list(config.mapping.schemas.values()) == ["mv_dt_good"]


def test_missing_live_result_is_not_a_pass():
    with pytest.raises(AssertionError, match="No checksum result"):
        find_result(SimpleNamespace(results=[]), "checksum", "dt_integer")


@pytest.mark.parametrize("scenario", ["good", "bad", "shape"])
def test_live_assertions_reject_false_passes(scenario):
    case = next(case for case in CASES if case.table == "dt_integer")
    results = []
    for prefix, suffix, source, target, status in (
        ("row_count", "", 4, 4, "PASS"),
        ("null_count", ".value", 1, 1, "PASS"),
        ("column", ".value", None, None, "FAIL" if scenario == "shape" else "PASS"),
        ("checksum", "", None, None, "PASS" if scenario == "good" else "FAIL"),
        ("aggregate", ".value", None, None, "PASS" if scenario == "good" else "FAIL"),
    ):
        result = SimpleNamespace(check_id=f"{prefix}:mv_dt_source.dt_integer{suffix}",
                                 source_value=source, target_value=target,
                                 status=SimpleNamespace(value=status), model_dump=lambda: {})
        results.append(result)
    report = SimpleNamespace(results=results, source=SimpleNamespace(version="PostgreSQL 16"),
                             target=SimpleNamespace(version="PostgreSQL 17"))
    def record(*args):
        pass
    check_live_case((report, "postgres_postgres", scenario), case, record)
    selected = next(result for result in results if result.check_id.startswith(
        "column:" if scenario == "shape" else "checksum:"))
    selected.status.value = "FAIL" if scenario == "good" else "PASS"
    with pytest.raises(AssertionError):
        check_live_case((report, "postgres_postgres", scenario), case, record)