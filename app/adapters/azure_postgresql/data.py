"""PostgreSQL data access (row counts and sampling)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.adapters._profile import (
    KeyRange,
    ProfileRequest,
    TableProfile,
    run_key_range,
    run_profile,
)
from app.adapters.azure_postgresql.type_mapping import quote_identifier
from app.models.database import QueryResult

Fetch = Callable[[str, dict | None], Awaitable[QueryResult]]


class PostgreSQLDataAccessor:
    """Reads data-level facts from PostgreSQL."""

    def __init__(self, fetch: Fetch) -> None:
        self._fetch = fetch

    async def get_row_count(self, schema: str, table: str) -> int:
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        result = await self._fetch(f"SELECT COUNT(*) FROM {qualified}", None)
        value = result.scalar()
        return int(value) if value is not None else 0

    async def get_row_count_estimate(self, schema: str, table: str) -> int | None:
        # reltuples is planner statistics: approximate, and negative until the first ANALYZE.
        # For a partitioned table the parent has no statistics, so sum its partitions.
        result = await self._fetch(
            """
            SELECT CASE WHEN c.relkind = 'p' THEN (
                       SELECT sum(GREATEST(ch.reltuples, 0))::bigint
                       FROM pg_inherits i JOIN pg_class ch ON ch.oid = i.inhrelid
                       WHERE i.inhparent = c.oid)
                   ELSE c.reltuples::bigint END
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %(schema)s AND c.relname = %(table)s
            """,
            {"schema": schema, "table": table},
        )
        value = result.scalar()
        return int(value) if value is not None and int(value) >= 0 else None

    async def get_table_profile(
        self,
        schema: str,
        table: str,
        request: ProfileRequest,
        key_range: KeyRange | None = None,
    ) -> TableProfile:
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        return await run_profile(
            self._fetch, request, qualified, quote_identifier, "COUNT", key_range
        )

    async def get_key_range(self, schema: str, table: str, column: str):
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        return await run_key_range(self._fetch, qualified, quote_identifier(column))

    async def get_null_count_estimates(
        self, schema: str, table: str, columns: list[str]
    ) -> dict[str, int]:
        # null_frac x reltuples: planner statistics, approximate and absent before ANALYZE.
        result = await self._fetch(
            """
            SELECT s.attname, s.null_frac, c.reltuples
            FROM pg_stats s
            JOIN pg_namespace n ON n.nspname = s.schemaname
            JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = s.tablename
            WHERE s.schemaname = %(schema)s AND s.tablename = %(table)s
            """,
            {"schema": schema, "table": table},
        )
        wanted = set(columns)
        return {
            name: round(float(fraction) * float(tuples))
            for name, fraction, tuples in result.rows
            if name in wanted and fraction is not None and tuples is not None and tuples >= 0
        }

    async def get_null_counts(
        self, schema: str, table: str, columns: list[str]
    ) -> dict[str, int]:
        if not columns:
            return {}
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        exprs = ", ".join(f"COUNT(*) - COUNT({quote_identifier(c)})" for c in columns)
        result = await self._fetch(f"SELECT {exprs} FROM {qualified}", None)
        row = result.rows[0] if result.rows else ()
        return {c: (int(v) if v is not None else 0) for c, v in zip(columns, row, strict=False)}

    async def get_numeric_aggregates(
        self, schema: str, table: str, column: str
    ) -> dict[str, object]:
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        col = quote_identifier(column)
        sql = f"SELECT MIN({col}), MAX({col}), SUM({col}), COUNT({col}) FROM {qualified}"
        result = await self._fetch(sql, None)
        row = result.rows[0] if result.rows else (None, None, None, 0)
        return {"min": row[0], "max": row[1], "sum": row[2], "count": row[3]}

    async def fetch_rows(
        self,
        schema: str,
        table: str,
        columns: list[str],
        order_by: list[str],
        limit: int | None = None,
    ) -> list[tuple]:
        if not columns:
            return []
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        select = ", ".join(quote_identifier(c) for c in columns)
        order_cols = order_by or columns
        order = ", ".join(quote_identifier(c) for c in order_cols)
        sql = f"SELECT {select} FROM {qualified} ORDER BY {order}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        result = await self._fetch(sql, None)
        return list(result.rows)

    async def count_orphans(
        self,
        child_schema: str,
        child_table: str,
        fk_columns: list[str],
        ref_schema: str | None,
        ref_table: str,
        ref_columns: list[str],
    ) -> int:
        sql = _orphan_sql(
            child_schema, child_table, fk_columns, ref_schema, ref_table, ref_columns
        )
        result = await self._fetch(sql, None)
        value = result.scalar()
        return int(value) if value is not None else 0


def _orphan_sql(
    child_schema: str,
    child_table: str,
    fk_columns: list[str],
    ref_schema: str | None,
    ref_table: str,
    ref_columns: list[str],
) -> str:
    """ANSI ``NOT EXISTS`` orphan-count query (identifiers quoted for PostgreSQL)."""
    child = f"{quote_identifier(child_schema)}.{quote_identifier(child_table)}"
    parent_name = (
        f"{quote_identifier(ref_schema)}.{quote_identifier(ref_table)}"
        if ref_schema
        else quote_identifier(ref_table)
    )
    not_null = " AND ".join(f'c.{quote_identifier(c)} IS NOT NULL' for c in fk_columns)
    join = " AND ".join(
        f"p.{quote_identifier(rc)} = c.{quote_identifier(fc)}"
        for fc, rc in zip(fk_columns, ref_columns, strict=False)
    )
    return (
        f"SELECT COUNT(*) FROM {child} c "
        f"WHERE {not_null} "
        f"AND NOT EXISTS (SELECT 1 FROM {parent_name} p WHERE {join})"
    )
