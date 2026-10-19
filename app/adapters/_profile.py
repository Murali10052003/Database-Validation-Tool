"""Single-scan table profiles.

One statement per table returns the row count, the non-NULL count of each requested
column and MIN/MAX/SUM/COUNT of each requested numeric column, instead of one full scan
for each of them. Adapters supply identifier quoting, the count function, and an
optional non-NULL count expression for database-specific datatype restrictions.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.models.database import QueryResult

# Oracle rejects a SELECT list of more than 1,000 expressions; stay safely below it.
MAX_EXPRESSIONS = 900

Fetch = Callable[[str, Any], Awaitable[QueryResult]]


@dataclass(frozen=True)
class ProfileRequest:
    """What to measure for one table (column names are the real names on that side)."""

    count: bool = False
    null_columns: tuple[str, ...] = ()
    aggregate_columns: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.count or self.null_columns or self.aggregate_columns)


@dataclass(frozen=True)
class KeyRange:
    """Rows with ``low <= column < high``; a ``None`` bound leaves that side open."""

    column: str
    low: int | None = None
    high: int | None = None


@dataclass
class TableProfile:
    row_count: int | None = None
    null_counts: dict[str, int] = field(default_factory=dict)
    aggregates: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileStatement:
    sql: str
    slots: tuple[tuple[str, str | None], ...]


def build_profile_statements(
    request: ProfileRequest,
    qualified_table: str,
    quote: Callable[[str], str],
    count_function: str = "COUNT",
    key_range: KeyRange | None = None,
    *,
    nonnull_count: Callable[[str], str] | None = None,
) -> list[ProfileStatement]:
    """Build the statement(s) for ``request``; wide requests are split to stay under limits."""
    with_rows = request.count or bool(request.null_columns)
    units: list[list[tuple[str, str, str]]] = []
    for column in request.null_columns:
        quoted = quote(column)
        expression = nonnull_count(quoted) if nonnull_count else f"{count_function}({quoted})"
        units.append([("nonnull", column, expression)])
    for column in request.aggregate_columns:
        q = quote(column)
        units.append([
            ("min", column, f"MIN({q})"),
            ("max", column, f"MAX({q})"),
            ("sum", column, f"SUM({q})"),
            ("count", column, f"{count_function}({q})"),
        ])
    where = _where(key_range, quote)
    statements: list[ProfileStatement] = []
    current: list[tuple[str, str, str]] = []

    def flush() -> None:
        if not current and not with_rows:
            return
        expressions = ([f"{count_function}(*)"] if with_rows else []) + [e for *_, e in current]
        slots = ((("rows", None),) if with_rows else ()) + tuple((k, c) for k, c, _ in current)
        statements.append(ProfileStatement(
            f"SELECT {', '.join(expressions)} FROM {qualified_table}{where}", slots,
        ))
        current.clear()

    for unit in units:
        if current and len(current) + len(unit) + 1 > MAX_EXPRESSIONS:
            flush()
        current.extend(unit)
    flush()
    return statements


def _where(key_range: KeyRange | None, quote: Callable[[str], str]) -> str:
    if key_range is None:
        return ""
    column = quote(key_range.column)
    conditions = []
    if key_range.low is not None:
        conditions.append(f"{column} >= {int(key_range.low)}")
    if key_range.high is not None:
        conditions.append(f"{column} < {int(key_range.high)}")
    return f" WHERE {' AND '.join(conditions)}" if conditions else ""


def parse_profile(
    statements: list[ProfileStatement], rows: list[tuple | None]
) -> TableProfile:
    """Turn the single result row of each statement into one :class:`TableProfile`."""
    profile = TableProfile()
    for statement, row in zip(statements, rows, strict=True):
        values = list(row) if row is not None else [None] * len(statement.slots)
        total = 0
        aggregates: dict[str, dict[str, Any]] = {}
        for (kind, column), value in zip(statement.slots, values, strict=True):
            if kind == "rows":
                total = int(value) if value is not None else 0
                if profile.row_count is None:
                    profile.row_count = total
            elif kind == "nonnull":
                profile.null_counts[column or ""] = total - (int(value) if value is not None else 0)
            else:
                aggregates.setdefault(column or "", {"min": None, "max": None,
                                                     "sum": None, "count": 0})[kind] = (
                    (int(value) if value is not None else 0) if kind == "count" else value
                )
        profile.aggregates.update(aggregates)
    return profile


async def run_profile(
    fetch: Fetch,
    request: ProfileRequest,
    qualified_table: str,
    quote: Callable[[str], str],
    count_function: str = "COUNT",
    key_range: KeyRange | None = None,
    *,
    nonnull_count: Callable[[str], str] | None = None,
) -> TableProfile:
    statements = build_profile_statements(
        request, qualified_table, quote, count_function, key_range,
        nonnull_count=nonnull_count,
    )
    rows: list[tuple | None] = []
    for statement in statements:
        result = await fetch(statement.sql, None)
        rows.append(result.rows[0] if result.rows else None)
    return parse_profile(statements, rows)


async def run_key_range(
    fetch: Fetch, qualified_table: str, quoted_column: str
) -> tuple[Any, Any] | None:
    """``(min, max)`` of a key column, or ``None`` for an empty table (index lookup)."""
    result = await fetch(
        f"SELECT MIN({quoted_column}), MAX({quoted_column}) FROM {qualified_table}", None
    )
    row = result.rows[0] if result.rows else (None, None)
    return None if row[0] is None or row[1] is None else (row[0], row[1])


def empty_profile(request: ProfileRequest) -> TableProfile:
    return TableProfile(
        row_count=0 if request.count else None,
        null_counts={c: 0 for c in request.null_columns},
        aggregates={c: {"min": None, "max": None, "sum": None, "count": 0}
                    for c in request.aggregate_columns},
    )


def split_key_range(column: str, low: Any, high: Any, chunks: int) -> list[KeyRange]:
    """Cover the whole key space with ``chunks`` ranges; the end ranges are open-ended."""
    first, last = math.floor(low), math.floor(high)
    span = last - first + 1
    count = min(chunks, span)
    if count < 2:
        return [KeyRange(column)]
    step = math.ceil(span / count)
    bounds = [first + step * i for i in range(1, count)]
    edges: list[int | None] = [None, *bounds, None]
    return [KeyRange(column, edges[i], edges[i + 1]) for i in range(count)]


def merge_profiles(parts: list[TableProfile]) -> TableProfile:
    """Combine profiles of disjoint row ranges of the same table (counts and sums add)."""
    merged = TableProfile()
    counts = [p.row_count for p in parts if p.row_count is not None]
    merged.row_count = sum(counts) if counts else None
    for column in {c for p in parts for c in p.null_counts}:
        merged.null_counts[column] = sum(p.null_counts.get(column, 0) for p in parts)
    for column in {c for p in parts for c in p.aggregates}:
        items = [p.aggregates[column] for p in parts if column in p.aggregates]
        mins = [i["min"] for i in items if i["min"] is not None]
        maxes = [i["max"] for i in items if i["max"] is not None]
        sums = [i["sum"] for i in items if i["sum"] is not None]
        merged.aggregates[column] = {
            "min": min(mins) if mins else None,
            "max": max(maxes) if maxes else None,
            "sum": sum(sums) if sums else None,
            "count": sum(int(i["count"] or 0) for i in items),
        }
    return merged
