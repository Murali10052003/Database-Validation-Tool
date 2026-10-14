"""Row-count fallback: exact COUNT(*) timeout -> database statistics estimate -> WARNING."""

from __future__ import annotations

import pytest

from app.core.enums import DatabaseType, ValidationStatus
from app.core.exceptions import QueryError, QueryTimeoutError
from app.models.schema import SchemaModel
from app.validators.row_count import RowCountValidator
from tests.conftest import MockAdapter
from tests.validators.test_row_count import _ctx, _model, _table


class CountAdapter(MockAdapter):
    """Adapter whose exact count can time out or fail, with an optional estimate."""

    def __init__(self, db_type, schemas, *, exact=100, estimate=None, fails_with=None):
        super().__init__(db_type, schemas)
        self.exact = exact
        self.estimate = estimate
        self.fails_with = fails_with
        self.estimate_calls = 0
        self.timeouts_seen: list[float] = []

    async def get_row_count_with_timeout(self, schema, table, timeout_seconds):
        self.timeouts_seen.append(timeout_seconds)
        if self.fails_with is not None:
            raise self.fails_with
        return self.exact

    async def get_row_count_estimate(self, schema, table):
        self.estimate_calls += 1
        return self.estimate


def _run(source: CountAdapter, target: CountAdapter, strategy: str | None = None):
    src_tables = [_table("HR", "EMP", 0)]
    tgt_tables = [_table("hr", "emp", 0)]
    ctx = _ctx(
        source, target,
        _model(DatabaseType.ORACLE, "HR", src_tables),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_tables),
    )
    if strategy:
        ctx.config.validation.data.row_count_strategy = strategy
    return RowCountValidator().validate(ctx)


def _pair(**overrides):
    source = CountAdapter(DatabaseType.ORACLE, [SchemaModel(name="HR")],
                          **overrides.get("source", {}))
    target = CountAdapter(DatabaseType.AZURE_POSTGRESQL, [SchemaModel(name="hr")],
                          **overrides.get("target", {}))
    return source, target


TIMEOUT = QueryTimeoutError("Row count of HR.EMP exceeded 300s")


async def test_timeout_falls_back_to_the_statistics_estimate_and_warns():
    source, target = _pair(source={"fails_with": TIMEOUT, "estimate": 1_000_000},
                           target={"exact": 1_000_050})
    (result,) = await _run(source, target)
    assert result.status == ValidationStatus.WARNING
    assert (result.source_value, result.target_value) == (1_000_000, 1_000_050)
    assert result.coverage.mode == "statistics_estimate"
    assert result.coverage.source_estimated is True
    assert result.coverage.target_estimated is False
    assert "estimated" in result.differences[0] and "not verified" in result.differences[0]
    assert "300s" in result.differences[0]
    assert source.estimate_calls == 1 and target.estimate_calls == 0
    assert source.timeouts_seen == [300]  # validation.data.timeout_seconds default


async def test_estimate_is_never_reported_as_pass_even_when_counts_agree():
    source, target = _pair(source={"fails_with": TIMEOUT, "estimate": 500},
                           target={"fails_with": TIMEOUT, "estimate": 500})
    (result,) = await _run(source, target)
    assert result.status == ValidationStatus.WARNING
    assert result.coverage.source_estimated and result.coverage.target_estimated
    assert len(result.differences) == 1  # no "counts differ" note when they agree


async def test_exact_counts_still_pass_and_never_ask_for_an_estimate():
    source, target = _pair(source={"exact": 7}, target={"exact": 7})
    (result,) = await _run(source, target)
    assert result.status == ValidationStatus.PASS
    assert result.coverage.mode == "database_count"
    assert source.estimate_calls == target.estimate_calls == 0


async def test_timeout_without_statistics_is_an_error_that_says_why():
    source, target = _pair(source={"fails_with": TIMEOUT, "estimate": None})
    (result,) = await _run(source, target)
    assert result.status == ValidationStatus.ERROR
    assert "no database statistics" in result.error and "exceeded 300s" in result.error


async def test_exact_strategy_reports_a_timeout_as_error_without_estimating():
    source, target = _pair(source={"fails_with": TIMEOUT, "estimate": 5})
    (result,) = await _run(source, target, strategy="exact")
    assert result.status == ValidationStatus.ERROR
    assert source.estimate_calls == 0


async def test_non_timeout_failures_are_errors_not_estimates():
    source, target = _pair(source={"fails_with": QueryError("ORA-00942: table does not exist"),
                                   "estimate": 5})
    (result,) = await _run(source, target)
    assert result.status == ValidationStatus.ERROR
    assert "ORA-00942" in result.error
    assert source.estimate_calls == 0


async def test_default_adapter_enforces_a_client_side_timeout():
    import asyncio

    class Slow(MockAdapter):
        async def get_row_count(self, schema, table):
            await asyncio.sleep(5)
            return 1

    with pytest.raises(QueryTimeoutError, match="exceeded 0.05s"):
        await Slow(DatabaseType.ORACLE, []).get_row_count_with_timeout("HR", "EMP", 0.05)
    assert await MockAdapter(DatabaseType.ORACLE, []).get_row_count_with_timeout("HR", "X", 0) == 0
    assert await MockAdapter(DatabaseType.ORACLE, []).get_row_count_estimate("HR", "X") is None
