"""Profiler: selection-driven single scans, timeout fallbacks, concurrency and cleanup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.adapters._profile import KeyRange, ProfileRequest, TableProfile
from app.adapters.factory import adapter_factory
from app.core.enums import DatabaseType, LogicalType, ValidationProfile, ValidationStatus
from app.core.exceptions import QueryError, QueryTimeoutError
from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel, ConstraintType
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel
from app.validators.aggregate import AggregateValidator
from app.validators.null_count import NullCountValidator
from app.validators.profiling import job_outcome
from app.validators.row_count import RowCountValidator
from tests.conftest import MockAdapter
from tests.validators.test_data_validators import _ctx

ALL = ("row_count", "null_count", "aggregate")


class Tracker:
    def __init__(self) -> None:
        self.current = 0
        self.peak = 0


class FakeDb(MockAdapter):
    """A table of ``rows`` ids (1..rows); AMT equals the id; the first ``null_rows`` are NULL."""

    def __init__(self, db_type, *, rows=100, null_rows=0, scan_timeout=False,
                 chunk_timeout=False, count_times_out=False, row_estimate=None,
                 null_estimates=None, key_range=(1, 100), aggregate_error=None,
                 delay=0.0, tracker=None) -> None:
        super().__init__(db_type, [])
        self.rows, self.null_rows = rows, null_rows
        self.scan_timeout, self.chunk_timeout = scan_timeout, chunk_timeout
        self.count_times_out = count_times_out
        self.row_estimate, self.null_estimates = row_estimate, null_estimates or {}
        self.key_range, self.aggregate_error = key_range, aggregate_error
        self.delay, self.tracker = delay, tracker
        self.profile_calls: list[tuple[ProfileRequest, KeyRange | None]] = []
        self.key_range_calls = 0
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def get_table_profile(self, schema, table, request, key_range=None):
        self.profile_calls.append((request, key_range))
        if self.tracker:
            self.tracker.current += 1
            self.tracker.peak = max(self.tracker.peak, self.tracker.current)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if key_range is None and self.scan_timeout:
                raise QueryTimeoutError(f"Profile of {schema}.{table} exceeded 300s")
            if key_range is not None and self.chunk_timeout:
                raise QueryTimeoutError(f"Chunk of {schema}.{table} exceeded 300s")
            if key_range is None and self.aggregate_error and request.aggregate_columns:
                raise self.aggregate_error
            low = max(1, key_range.low) if key_range and key_range.low is not None else 1
            high = (min(self.rows + 1, key_range.high)
                    if key_range and key_range.high is not None else self.rows + 1)
            ids = list(range(low, max(low, high)))
            profile = TableProfile(row_count=len(ids))
            for column in request.null_columns:
                profile.null_counts[column] = sum(1 for i in ids if i <= self.null_rows)
            for column in request.aggregate_columns:
                profile.aggregates[column] = {
                    "min": min(ids) if ids else None, "max": max(ids) if ids else None,
                    "sum": sum(ids) if ids else None, "count": len(ids)}
            return profile
        finally:
            if self.tracker:
                self.tracker.current -= 1

    async def get_row_count(self, schema, table):
        if self.count_times_out:
            raise QueryTimeoutError(f"Row count of {schema}.{table} exceeded 300s")
        return self.rows

    async def get_row_count_estimate(self, schema, table):
        return self.row_estimate

    async def get_null_count_estimates(self, schema, table, columns):
        return {c: self.null_estimates[c] for c in columns if c in self.null_estimates}

    async def get_key_range(self, schema, table, column):
        self.key_range_calls += 1
        return self.key_range


def _columns(lower: bool, *, nullable: bool = True) -> list[ColumnModel]:
    def column(name, position, ltype, null):
        return ColumnModel(name=name.lower() if lower else name, ordinal_position=position,
                           native_type="t", logical_type=ltype, nullable=null)

    return [column("ID", 1, LogicalType.INTEGER, False),
            column("AMT", 2, LogicalType.DECIMAL, nullable),
            column("NAME", 3, LogicalType.STRING, nullable)]


def _model(db_type, schema, lower, names, *, pk=True, nullable=True) -> DatabaseModel:
    tables = []
    for name in names:
        table_name = name.lower() if lower else name
        tables.append(TableModel(
            schema_name=schema, name=table_name, columns=_columns(lower, nullable=nullable),
            constraints=[ConstraintModel(
                name="PK", constraint_type=ConstraintType.PRIMARY_KEY,
                columns=["id" if lower else "ID"])] if pk else [],
        ))
    return DatabaseModel(database_type=db_type, schemas=[SchemaModel(name=schema, tables=tables)])


def _setup(source: FakeDb, target: FakeDb, selected=ALL, *, names=("T1",), pk=True,
           nullable=True):
    ctx = _ctx(source, target,
               _model(DatabaseType.ORACLE, "HR", False, names, pk=pk, nullable=nullable),
               _model(DatabaseType.AZURE_POSTGRESQL, "hr", True, names, pk=pk,
                      nullable=nullable))
    ctx.selected_checks = frozenset(selected)
    return ctx


def _pair(**overrides):
    return (FakeDb(DatabaseType.ORACLE, **overrides.get("source", {})),
            FakeDb(DatabaseType.AZURE_POSTGRESQL, **overrides.get("target", {})))


async def _run(ctx):
    validators = {"row_count": RowCountValidator(), "null_count": NullCountValidator(),
                  "aggregate": AggregateValidator()}
    results = {key: await validators[key].validate(ctx) for key in ALL if key in ctx.selected_checks}
    outcome = await job_outcome(ctx, "HR", "T1")
    await ctx.close_profiling()
    return results, outcome


def _statuses(results):
    return {key: [r.status for r in value] for key, value in results.items()}


# -- selection drives the scan --------------------------------------------------------


@pytest.mark.parametrize(("selected", "expected"), [
    (("row_count",), ProfileRequest(count=True)),
    # ID is NOT NULL on both sides, so it is never scanned for NULLs
    (("null_count",), ProfileRequest(null_columns=("AMT", "NAME"))),
    # ID is a key column, NAME is not numeric
    (("aggregate",), ProfileRequest(aggregate_columns=("AMT",))),
    (ALL, ProfileRequest(True, ("AMT", "NAME"), ("AMT",))),
])
async def test_the_scan_asks_only_for_what_the_selected_checks_need(selected, expected):
    source, target = _pair()
    results, _ = await _run(_setup(source, target, selected))
    assert [call[0] for call in source.profile_calls] == [expected]
    assert [call[0].count for call in target.profile_calls] == [expected.count]
    assert all(r.status == ValidationStatus.PASS for value in results.values() for r in value)


async def test_all_three_checks_share_one_scan_per_side_instead_of_2_plus_k():
    source, target = _pair()
    source.get_numeric_aggregates = _forbid
    source.get_null_counts = _forbid
    await _run(_setup(source, target))
    assert len(source.profile_calls) == 1 and len(target.profile_calls) == 1


async def _forbid(*args, **kwargs):
    raise AssertionError("per-check query used instead of the shared scan")


async def test_columns_not_null_on_both_sides_need_no_scan_at_all():
    source, target = _pair()
    ctx = _setup(source, target, ("null_count",), nullable=False)
    results, _ = await _run(ctx)
    assert source.profile_calls == [] and target.profile_calls == []
    assert all(r.status == ValidationStatus.PASS for r in results["null_count"])
    assert all("NOT NULL" in r.validation_scope for r in results["null_count"])
    assert all((r.source_value, r.target_value) == (0, 0) for r in results["null_count"])


async def test_a_nullable_target_still_gets_scanned_when_the_source_is_not_null():
    source, target = _pair(source={"null_rows": 0}, target={"null_rows": 3})
    ctx = _setup(source, target, ("null_count",))
    ctx.target_model.schemas[0].tables[0].columns[1].nullable = True
    ctx.source_model.schemas[0].tables[0].columns[1].nullable = False  # AMT: NOT NULL only on source
    results, _ = await _run(ctx)
    amt = next(r for r in results["null_count"] if r.source_object.endswith(".AMT"))
    assert (amt.source_value, amt.target_value) == (0, 3) and amt.status == ValidationStatus.FAIL


# -- timeout fallbacks ----------------------------------------------------------------


async def test_a_timed_out_scan_is_retried_over_key_ranges_and_stays_exact():
    source, target = _pair(source={"scan_timeout": True, "null_rows": 10},
                           target={"null_rows": 10})
    ctx = _setup(source, target)
    ctx.config.validation.data.fallback_chunks = 4
    results, outcome = await _run(ctx)
    assert _statuses(results) == {"row_count": [ValidationStatus.PASS],
                                  "null_count": [ValidationStatus.PASS] * 3,  # ID, AMT, NAME
                                  "aggregate": [ValidationStatus.PASS]}
    assert outcome.source.mode == "chunked" and outcome.target.mode == "single_scan"
    assert source.key_range_calls == 1
    ranges = [(c[1].low, c[1].high) for c in source.profile_calls if c[1] is not None]
    assert ranges == [(None, 26), (26, 51), (51, 76), (76, None)]
    assert not any(r.coverage and r.coverage.mode == "statistics_estimate"
                   for value in results.values() for r in value)


async def test_chunking_needs_a_single_integer_primary_key():
    source, target = _pair(source={"scan_timeout": True, "row_estimate": 500,
                                   "null_estimates": {"AMT": 0, "NAME": 0}},
                           target={"rows": 500})
    results, outcome = await _run(_setup(source, target, pk=False))
    assert source.key_range_calls == 0  # no key: not even tried
    assert outcome.source.mode == "fallback"


async def test_without_chunking_the_count_is_exact_alone_nulls_are_estimates_aggregates_time_out():
    source, target = _pair(source={"scan_timeout": True, "null_estimates": {"AMT": 0, "NAME": 0}})
    results, outcome = await _run(_setup(source, target, pk=False))
    (count,) = results["row_count"]
    assert count.status == ValidationStatus.PASS and count.coverage.mode == "database_count"
    # ID is NOT NULL on both sides (known zero, PASS); AMT and NAME came from statistics
    assert [r.status for r in results["null_count"]] == [
        ValidationStatus.PASS, ValidationStatus.WARNING, ValidationStatus.WARNING]
    estimated = [r for r in results["null_count"] if r.coverage]
    assert all(r.coverage.mode == "statistics_estimate" and r.coverage.source_estimated
               and not r.coverage.target_estimated for r in estimated)
    assert len(estimated) == 2
    assert results["aggregate"]
    assert all(r.status == ValidationStatus.ERROR and "exceeded 300s" in r.error
               for r in results["aggregate"])


async def test_row_count_estimate_is_used_only_after_an_exact_count_also_times_out():
    source, target = _pair(
        source={"scan_timeout": True, "count_times_out": True, "row_estimate": 100},
        target={"rows": 100})
    results, _ = await _run(_setup(source, target, ("row_count",), pk=False))
    (result,) = results["row_count"]
    assert result.status == ValidationStatus.WARNING
    assert result.coverage.mode == "statistics_estimate" and result.coverage.source_estimated


async def test_key_range_that_still_times_out_falls_back_to_estimates():
    source, target = _pair(source={"scan_timeout": True, "chunk_timeout": True,
                                   "count_times_out": True, "row_estimate": 100})
    results, outcome = await _run(_setup(source, target, ("row_count",)))
    assert outcome.source.mode == "fallback"
    assert results["row_count"][0].status == ValidationStatus.WARNING


async def test_chunking_can_be_disabled():
    source, target = _pair(source={"scan_timeout": True})
    ctx = _setup(source, target, ("row_count",))
    ctx.config.validation.data.fallback_chunks = 0
    results, _ = await _run(ctx)
    assert source.key_range_calls == 0
    assert results["row_count"][0].status == ValidationStatus.PASS  # exact count on its own


async def test_exact_strategy_never_substitutes_statistics():
    source, target = _pair(source={"scan_timeout": True, "count_times_out": True,
                                   "row_estimate": 100, "null_estimates": {"AMT": 0, "NAME": 0}})
    ctx = _setup(source, target, pk=False)
    ctx.config.validation.data.row_count_strategy = "exact"
    results, _ = await _run(ctx)
    assert all(r.status == ValidationStatus.ERROR for value in results.values() for r in value)
    assert "exceeded" in results["row_count"][0].error


async def test_no_statistics_means_an_error_that_says_so():
    source, target = _pair(source={"scan_timeout": True, "count_times_out": True})
    results, _ = await _run(_setup(source, target, ("row_count", "null_count"), pk=False))
    assert "no database statistics" in results["row_count"][0].error
    assert "no database statistics" in results["null_count"][0].error


async def test_a_failing_column_cannot_hide_the_other_measurements():
    source, target = _pair(source={"aggregate_error": QueryError("ORA-01426: numeric overflow")})
    results, outcome = await _run(_setup(source, target))
    assert [r.status for r in results["row_count"]] == [ValidationStatus.PASS]
    assert [r.status for r in results["null_count"]] == [ValidationStatus.PASS] * 3
    (aggregate,) = results["aggregate"]
    assert aggregate.status == ValidationStatus.ERROR and "ORA-01426" in aggregate.error
    assert outcome.source.mode == "isolated"


async def test_very_large_tables_are_skipped_for_column_checks_but_still_counted():
    source, target = _pair(source={"row_estimate": 1_000_000})
    ctx = _setup(source, target)
    ctx.config.validation.data.max_table_rows_for_column_checks = 50_000
    results, _ = await _run(ctx)
    assert [r.status for r in results["row_count"]] == [ValidationStatus.PASS]
    for key in ("null_count", "aggregate"):
        (skipped,) = results[key]
        assert skipped.status == ValidationStatus.SKIPPED
        assert "1,000,000" in skipped.message and "50,000" in skipped.message
    assert source.profile_calls[0][0] == ProfileRequest(count=True)


# -- concurrency and cleanup ----------------------------------------------------------


async def test_tables_are_profiled_concurrently_in_order_and_extra_connections_are_closed(
    monkeypatch,
):
    tracker = Tracker()
    created: list[FakeDb] = []

    def make(db_type):
        adapter = FakeDb(db_type, delay=0.05,
                         tracker=tracker if db_type == DatabaseType.ORACLE else None)
        created.append(adapter)
        return adapter

    monkeypatch.setattr(adapter_factory, "create", lambda config: config.make())
    source = FakeDb(DatabaseType.ORACLE, delay=0.05, tracker=tracker)
    target = FakeDb(DatabaseType.AZURE_POSTGRESQL, delay=0.05)
    source.config = SimpleNamespace(make=lambda: make(DatabaseType.ORACLE))
    target.config = SimpleNamespace(make=lambda: make(DatabaseType.AZURE_POSTGRESQL))
    names = [f"T{i}" for i in range(1, 7)]
    ctx = _setup(source, target, ("row_count",), names=names)
    ctx.config.validation.data.parallel_workers = 3

    results = await RowCountValidator().validate(ctx)
    assert [r.source_object for r in results] == [f"HR.{n}" for n in names]  # deterministic order
    assert all(r.status == ValidationStatus.PASS for r in results)
    assert tracker.peak == 3
    assert len(created) == 4 and not any(a.closed for a in created)
    await ctx.close_profiling()
    assert all(a.closed for a in created)
    assert ctx.profiles is None and ctx.profile_runner is None


async def test_unavailable_extra_connections_degrade_to_a_single_worker(monkeypatch):
    def refuse(config):
        raise OSError("too many connections")

    monkeypatch.setattr(adapter_factory, "create", refuse)
    source, target = _pair()
    source.config = target.config = SimpleNamespace()
    ctx = _setup(source, target, ("row_count",), names=["T1", "T2", "T3"])
    ctx.config.validation.data.parallel_workers = 4
    results = await RowCountValidator().validate(ctx)
    assert [r.status for r in results] == [ValidationStatus.PASS] * 3
    await ctx.close_profiling()


async def test_validators_used_on_their_own_keep_the_direct_per_query_path():
    source, target = _pair()
    ctx = _setup(source, target, ALL)
    ctx.selected_checks = None
    assert await job_outcome(ctx, "HR", "T1") is None
    results = await RowCountValidator().validate(ctx)
    assert results[0].status == ValidationStatus.PASS
    assert source.profile_calls == []


# -- measured: statements issued per table before and after ------------------------------


async def test_statement_count_with_the_real_oracle_accessor_before_and_after():
    from app.adapters.oracle.data import OracleDataAccessor
    from app.models.database import QueryResult

    statements: list[str] = []

    async def fetch(sql, params):
        statements.append(sql)
        select_list = sql[len("SELECT "):sql.index(" FROM ")]
        return QueryResult(rows=[(5,) * (select_list.count(",") + 1)])

    class OracleBacked(MockAdapter):
        def __init__(self, db_type):
            super().__init__(db_type, [])
            self.data = OracleDataAccessor(fetch)

        async def get_row_count(self, schema, table):
            return await self.data.get_row_count(schema, table)

        async def get_null_counts(self, schema, table, columns):
            return await self.data.get_null_counts(schema, table, columns)

        async def get_numeric_aggregates(self, schema, table, column):
            return await self.data.get_numeric_aggregates(schema, table, column)

        async def get_table_profile(self, schema, table, request, key_range=None):
            return await self.data.get_table_profile(schema, table, request, key_range)

    def models(lower):
        columns = [ColumnModel(name=("id" if lower else "ID"), ordinal_position=1,
                               native_type="t", logical_type=LogicalType.INTEGER, nullable=False)]
        columns += [ColumnModel(name=(f"m{i}" if lower else f"M{i}"), ordinal_position=i + 1,
                                native_type="t", logical_type=LogicalType.DECIMAL)
                    for i in range(1, 7)]
        table = TableModel(schema_name="hr" if lower else "HR", name="t" if lower else "T",
                           columns=columns, constraints=[ConstraintModel(
                               name="PK", constraint_type=ConstraintType.PRIMARY_KEY,
                               columns=["id" if lower else "ID"])])
        return DatabaseModel(database_type=DatabaseType.ORACLE,
                             schemas=[SchemaModel(name="hr" if lower else "HR", tables=[table])])

    async def measure(selected):
        ctx = _ctx(OracleBacked(DatabaseType.ORACLE), OracleBacked(DatabaseType.AZURE_POSTGRESQL),
                   models(False), models(True))
        # None = validators on their own, i.e. the old one-query-per-check behaviour
        ctx.selected_checks = selected
        statements.clear()
        validators = {"row_count": RowCountValidator(), "null_count": NullCountValidator(),
                      "aggregate": AggregateValidator()}
        results = {key: await validators[key].validate(ctx) for key in ALL}
        await ctx.close_profiling()
        assert all(r.status == ValidationStatus.PASS for value in results.values() for r in value)
        return len(statements)

    before = await measure(None)
    after = await measure(frozenset(ALL))
    # 6 nullable numeric columns: before = row count + NULL counts + 6 aggregate scans, per side
    assert before == 2 * (1 + 1 + 6)
    assert after == 2 * 1


# -- the other data queries are time-limited too --------------------------------------


async def test_checksum_and_orphan_queries_report_a_timeout_as_an_error():
    from app.validators.checksum import ChecksumValidator
    from app.validators.referential_integrity import ReferentialIntegrityValidator
    from tests.validators.test_data_validators import DataMock, _col, _model

    class SlowSource(DataMock):
        async def fetch_rows(self, *args, **kwargs):
            raise QueryTimeoutError("Checksum fetch of HR.T exceeded 300s")

        async def count_orphans(self, *args, **kwargs):
            raise QueryTimeoutError("Orphan count of hr.t (FK) exceeded 300s")

    table = TableModel(schema_name="HR", name="T", columns=[_col("ID", LogicalType.INTEGER)])
    target_table = TableModel(
        schema_name="hr", name="t", columns=[_col("id", LogicalType.INTEGER)],
        constraints=[ConstraintModel(
            name="FK", constraint_type=ConstraintType.FOREIGN_KEY, columns=["id"],
            references={"ref_table": "p", "ref_columns": ["id"]})],
    )
    source = SlowSource(DatabaseType.ORACLE, [])
    target = SlowSource(DatabaseType.AZURE_POSTGRESQL, [])
    ctx = _ctx(source, target, _model(DatabaseType.ORACLE, "HR", table),
               _model(DatabaseType.AZURE_POSTGRESQL, "hr", target_table))
    (checksum,) = await ChecksumValidator().validate(ctx)
    assert checksum.status == ValidationStatus.ERROR and "exceeded 300s" in checksum.error
    (orphans,) = await ReferentialIntegrityValidator().validate(ctx)
    assert orphans.status == ValidationStatus.ERROR and "exceeded 300s" in orphans.error


# -- engine: discovery follows the selected checks ------------------------------------


@pytest.mark.parametrize(("profile", "checks", "structural"), [
    (ValidationProfile.STANDARD, ["row_count"], False),  # was True: the profile forced it
    (ValidationProfile.FULL, ["null_count"], False),
    (ValidationProfile.QUICK, ["aggregate"], True),  # aggregates need constraints for keys
    (ValidationProfile.QUICK, ["constraints"], True),
])
async def test_engine_loads_structural_metadata_only_when_a_selected_check_needs_it(
    monkeypatch, profile, checks, structural,
):
    from app.services.validation_service import ValidationService
    from app.validators.engine import ValidationEngine

    source, target = _pair()
    ctx = _setup(source, target)
    ctx.config.validation.profile = profile
    ctx.config.validation.selected_checks = checks
    seen = {}

    async def discover(engine, context, **kwargs):
        seen.update(kwargs)
        context.source_model, context.target_model = ctx.source_model, ctx.target_model

    monkeypatch.setattr(ValidationEngine, "_discover", discover)
    monkeypatch.setattr("app.services.validation_service.adapter_factory.create",
                        lambda config: source if config.type == DatabaseType.ORACLE else target)
    await ValidationService().validate(ctx.config, "structural-rule")
    assert seen["include_structural"] is structural
