"""MySQL data access (row counts, aggregates, sampling, orphan counts)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.adapters._profile import (
    KeyRange,
    ProfileRequest,
    TableProfile,
    run_key_range,
    run_profile,
)
from app.adapters.mysql.type_mapping import quote_identifier
from app.models.database import QueryResult

Fetch = Callable[[str, dict | None], Awaitable[QueryResult]]


class MySQLDataAccessor:
    """Reads data-level facts from MySQL."""

    def __init__(self, fetch: Fetch) -> None:
        self._fetch = fetch

    async def get_row_count(self, schema: str, table: str) -> int:
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        result = await self._fetch(f"SELECT COUNT(*) FROM {qualified}", None)
        value = result.scalar()
        return int(value) if value is not None else 0

    async def get_row_count_estimate(self, schema: str, table: str) -> int | None:
        # TABLE_ROWS is an InnoDB estimate, NULL for views and unavailable statistics.
        result = await self._fetch(
            "SELECT table_rows FROM information_schema.tables "
            "WHERE table_schema = %(schema)s AND table_name = %(table)s",
            {"schema": schema, "table": table},
        )
        value = result.scalar()
        return int(value) if value is not None else None

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
        order = ", ".join(quote_identifier(c) for c in (order_by or columns))
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
        child = f"{quote_identifier(child_schema)}.{quote_identifier(child_table)}"
        parent = (
            f"{quote_identifier(ref_schema)}.{quote_identifier(ref_table)}"
            if ref_schema
            else quote_identifier(ref_table)
        )
        not_null = " AND ".join(f"c.{quote_identifier(c)} IS NOT NULL" for c in fk_columns)
        join = " AND ".join(
            f"p.{quote_identifier(rc)} = c.{quote_identifier(fc)}"
            for fc, rc in zip(fk_columns, ref_columns, strict=False)
        )
        sql = (
            f"SELECT COUNT(*) FROM {child} c "
            f"WHERE {not_null} "
            f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE {join})"
        )
        result = await self._fetch(sql, None)
        value = result.scalar()
        return int(value) if value is not None else 0
