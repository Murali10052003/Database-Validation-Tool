"""Single-scan profile: SQL building, parsing, wide-table splitting, chunk merging."""

from __future__ import annotations

import pytest

from app.adapters._profile import (
    MAX_EXPRESSIONS,
    KeyRange,
    ProfileRequest,
    TableProfile,
    build_profile_statements,
    empty_profile,
    merge_profiles,
    parse_profile,
    run_profile,
    split_key_range,
)
from app.adapters.azure_postgresql.data import PostgreSQLDataAccessor
from app.adapters.oracle.data import OracleDataAccessor
from app.adapters.sqlserver.data import SQLServerDataAccessor
from app.models.database import QueryResult


def quote(name: str) -> str:
    return f'"{name}"'


TABLE = '"HR"."EMP"'


def test_one_statement_covers_count_nulls_and_every_numeric_column():
    request = ProfileRequest(count=True, null_columns=("A", "B"), aggregate_columns=("N", "M"))
    (statement,) = build_profile_statements(request, TABLE, quote)
    assert statement.sql == (
        'SELECT COUNT(*), COUNT("A"), COUNT("B"), '
        'MIN("N"), MAX("N"), SUM("N"), COUNT("N"), '
        'MIN("M"), MAX("M"), SUM("M"), COUNT("M") FROM "HR"."EMP"'
    )


@pytest.mark.parametrize(("request_", "sql"), [
    (ProfileRequest(count=True), 'SELECT COUNT(*) FROM "HR"."EMP"'),
    (ProfileRequest(null_columns=("A",)), 'SELECT COUNT(*), COUNT("A") FROM "HR"."EMP"'),
    (ProfileRequest(aggregate_columns=("N",)),
     'SELECT MIN("N"), MAX("N"), SUM("N"), COUNT("N") FROM "HR"."EMP"'),
])
def test_single_check_requests_stay_as_small_as_the_old_queries(request_, sql):
    (statement,) = build_profile_statements(request_, TABLE, quote)
    assert statement.sql == sql


def test_empty_request_builds_nothing():
    assert build_profile_statements(ProfileRequest(), TABLE, quote) == []


def test_results_are_decoded_per_column():
    request = ProfileRequest(count=True, null_columns=("A", "B"), aggregate_columns=("N",))
    statements = build_profile_statements(request, TABLE, quote)
    profile = parse_profile(statements, [(10, 8, 10, 1, 9, 45, 9)])
    assert profile.row_count == 10
    assert profile.null_counts == {"A": 2, "B": 0}
    assert profile.aggregates == {"N": {"min": 1, "max": 9, "sum": 45, "count": 9}}


def test_empty_result_row_means_zero_rows_not_a_crash():
    statements = build_profile_statements(
        ProfileRequest(count=True, aggregate_columns=("N",)), TABLE, quote)
    profile = parse_profile(statements, [None])
    assert profile.row_count == 0
    assert profile.aggregates["N"] == {"min": None, "max": None, "sum": None, "count": 0}


def test_wide_requests_are_split_below_the_oracle_expression_limit():
    columns = tuple(f"C{i}" for i in range(2_500))
    statements = build_profile_statements(ProfileRequest(null_columns=columns), TABLE, quote)
    assert len(statements) > 1
    for statement in statements:
        assert statement.sql.count("COUNT(") <= MAX_EXPRESSIONS
        assert statement.slots[0] == ("rows", None)  # each part can derive its own NULL counts
    rows = [(1_000, *[1_000 - (i % 7)] * (len(s.slots) - 1)) for i, s in enumerate(statements)]
    profile = parse_profile(statements, rows)
    assert profile.row_count == 1_000
    assert set(profile.null_counts) == set(columns)


def test_aggregate_columns_are_never_split_across_statements():
    columns = tuple(f"N{i}" for i in range(500))
    statements = build_profile_statements(ProfileRequest(aggregate_columns=columns), TABLE, quote)
    for statement in statements:
        by_column: dict[str, int] = {}
        for _, column in statement.slots:
            if column:
                by_column[column] = by_column.get(column, 0) + 1
        assert set(by_column.values()) == {4}


def test_key_range_adds_a_bounded_where_clause_with_integer_literals():
    request = ProfileRequest(count=True)
    sql = lambda key_range: build_profile_statements(  # noqa: E731
        request, TABLE, quote, key_range=key_range)[0].sql
    assert sql(KeyRange("ID", 10, 20)).endswith('WHERE "ID" >= 10 AND "ID" < 20')
    assert sql(KeyRange("ID", None, 20)).endswith('WHERE "ID" < 20')
    assert sql(KeyRange("ID", 10, None)).endswith('WHERE "ID" >= 10')
    assert "WHERE" not in sql(KeyRange("ID"))


def test_split_key_range_covers_the_whole_key_space_with_open_ends():
    ranges = split_key_range("ID", 1, 100, 4)
    assert [(r.low, r.high) for r in ranges] == [(None, 26), (26, 51), (51, 76), (76, None)]
    assert split_key_range("ID", 5, 5, 8) == [KeyRange("ID")]  # one key: nothing to split
    assert len(split_key_range("ID", 1, 3, 32)) == 3  # never more ranges than keys
    # non-integral and negative keys are still fully covered
    ranges = split_key_range("ID", -2.5, 7.9, 3)
    assert ranges[0].low is None and ranges[-1].high is None


def test_chunk_profiles_merge_exactly():
    one = TableProfile(5, {"A": 1}, {"N": {"min": 3, "max": 9, "sum": 20, "count": 4}})
    two = TableProfile(7, {"A": 2}, {"N": {"min": 1, "max": 6, "sum": 15, "count": 7}})
    empty = TableProfile(0, {"A": 0}, {"N": {"min": None, "max": None, "sum": None, "count": 0}})
    merged = merge_profiles([one, two, empty])
    assert merged.row_count == 12
    assert merged.null_counts == {"A": 3}
    assert merged.aggregates["N"] == {"min": 1, "max": 9, "sum": 35, "count": 11}
    only_empty = merge_profiles([empty])
    assert only_empty.aggregates["N"]["min"] is None and only_empty.aggregates["N"]["sum"] is None


def test_empty_profile_has_zero_counts_and_no_aggregates():
    profile = empty_profile(ProfileRequest(True, ("A",), ("N",)))
    assert (profile.row_count, profile.null_counts) == (0, {"A": 0})
    assert profile.aggregates["N"]["sum"] is None


# -- accessors: one query per table, database-specific quoting and count function -----


def _recording_fetch(row: tuple):
    calls: list[str] = []

    async def fetch(sql: str, params):
        calls.append(sql)
        return QueryResult(rows=[row])

    return fetch, calls


@pytest.mark.parametrize(("accessor_class", "quoted", "count_fn"), [
    (OracleDataAccessor, '"HR"."EMP"', "COUNT("),
    (PostgreSQLDataAccessor, '"hr"."emp"', "COUNT("),
    (SQLServerDataAccessor, "[hr].[emp]", "COUNT_BIG("),
])
async def test_each_accessor_profiles_a_table_with_a_single_query(accessor_class, quoted, count_fn):
    fetch, calls = _recording_fetch((10, 8, 1, 9, 45, 9))
    accessor = accessor_class(fetch)
    name = ("HR", "EMP") if accessor_class is OracleDataAccessor else ("hr", "emp")
    profile = await accessor.get_table_profile(
        *name, ProfileRequest(count=True, null_columns=("A",), aggregate_columns=("N",)))
    assert len(calls) == 1
    assert quoted in calls[0] and count_fn in calls[0]
    assert (profile.row_count, profile.null_counts, profile.aggregates["N"]["sum"]) == (
        10, {"A": 2}, 45)


async def test_key_range_query_and_empty_table():
    fetch, calls = _recording_fetch((None, None))
    assert await OracleDataAccessor(fetch).get_key_range("HR", "EMP", "ID") is None
    assert calls == ['SELECT MIN("ID"), MAX("ID") FROM "HR"."EMP"']
    fetch, _ = _recording_fetch((3, 90))
    assert await PostgreSQLDataAccessor(fetch).get_key_range("hr", "emp", "id") == (3, 90)


@pytest.mark.parametrize("count", [False, True])
@pytest.mark.parametrize("rows", [0, 1000])
async def test_oracle_lob_null_profile_uses_scalar_case_counts(count, rows):
    fetch, calls = _recording_fetch((rows, rows * 3 // 4, rows * 4 // 5, 0, rows))
    profile = await OracleDataAccessor(fetch).get_table_profile(
        "HR", "EMP",
        ProfileRequest(count=count, null_columns=("BINARY_PAYLOAD", "TEXT_PAYLOAD", "ALL_NULL", 'A"B')),
        KeyRange("ID", 1, 1001),
    )
    assert calls == [
        'SELECT COUNT(*), COUNT(CASE WHEN "BINARY_PAYLOAD" IS NOT NULL THEN 1 END), '
        'COUNT(CASE WHEN "TEXT_PAYLOAD" IS NOT NULL THEN 1 END), '
        'COUNT(CASE WHEN "ALL_NULL" IS NOT NULL THEN 1 END), '
        'COUNT(CASE WHEN "A""B" IS NOT NULL THEN 1 END) '
        'FROM "HR"."EMP" WHERE "ID" >= 1 AND "ID" < 1001'
    ]
    assert profile.row_count == rows
    assert profile.null_counts == {
        "BINARY_PAYLOAD": rows // 4, "TEXT_PAYLOAD": rows // 5, "ALL_NULL": rows, 'A"B': 0,
    }


async def test_oracle_direct_null_counts_use_the_same_lob_safe_expression():
    fetch, calls = _recording_fetch((250, 200))
    counts = await OracleDataAccessor(fetch).get_null_counts(
        "HR", "EMP", ["BINARY_PAYLOAD", "TEXT_PAYLOAD"],
    )
    assert calls == [
        'SELECT COUNT(*) - COUNT(CASE WHEN "BINARY_PAYLOAD" IS NOT NULL THEN 1 END), '
        'COUNT(*) - COUNT(CASE WHEN "TEXT_PAYLOAD" IS NOT NULL THEN 1 END) FROM "HR"."EMP"'
    ]
    assert counts == {"BINARY_PAYLOAD": 250, "TEXT_PAYLOAD": 200}


async def test_run_profile_executes_each_split_statement():
    calls: list[str] = []

    async def fetch(sql: str, params):
        calls.append(sql)
        return QueryResult(rows=[(10,) * sql.count("COUNT(")])

    columns = tuple(f"C{i}" for i in range(1_000))
    profile = await run_profile(fetch, ProfileRequest(null_columns=columns), TABLE, quote)
    assert len(calls) == 2
    assert profile.row_count == 10 and len(profile.null_counts) == 1_000


# -- NULL-count statistics ------------------------------------------------------------


async def test_oracle_null_estimates_use_column_statistics_and_skip_missing():
    async def fetch(sql, params):
        assert "all_tab_col_statistics" in sql
        assert params == {"owner": "HR", "table_name": "EMP"}
        return QueryResult(rows=[("A", 12), ("B", None), ("OTHER", 5)])

    estimates = await OracleDataAccessor(fetch).get_null_count_estimates("HR", "EMP", ["A", "B"])
    assert estimates == {"A": 12}


async def test_postgres_null_estimates_scale_null_fraction_by_reltuples():
    async def fetch(sql, params):
        assert "pg_stats" in sql
        return QueryResult(rows=[("a", 0.25, 1000.0), ("b", 0.5, -1.0), ("c", None, 10.0)])

    estimates = await PostgreSQLDataAccessor(fetch).get_null_count_estimates(
        "hr", "emp", ["a", "b", "c"])
    assert estimates == {"a": 250}  # never-analyzed (-1) and fraction-less columns omitted
