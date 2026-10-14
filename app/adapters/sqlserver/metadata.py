"""SQL Server metadata collection.

Uses ``INFORMATION_SCHEMA`` for schemas/tables/columns/PK/unique constraints and the
``sys`` catalog for foreign keys and indexes. Queries use positional ``?``
placeholders (pyodbc paramstyle); collector methods pass parameters as tuples.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.adapters._helpers import schema_name_filter
from app.core.enums import DatabaseType, GeneratedValueStrategy
from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel, ConstraintType, ForeignKeyReference
from app.models.database import QueryResult
from app.models.index import IndexColumn, IndexModel
from app.models.schema import SchemaModel
from app.models.table import TableModel
from app.normalization.datatypes import TypeNormalizer
from app.normalization.identifiers import normalize_identifier

Fetch = Callable[[str, tuple | None], Awaitable[QueryResult]]

SCHEMAS_SQL = """
    SELECT s.name
    FROM sys.schemas s
    WHERE s.name NOT IN (
        'sys', 'INFORMATION_SCHEMA', 'guest', 'db_owner', 'db_accessadmin',
        'db_securityadmin', 'db_ddladmin', 'db_backupoperator', 'db_datareader',
        'db_datawriter', 'db_denydatareader', 'db_denydatawriter'
    )
    ORDER BY s.name
"""


def schemas_filtered_sql(count: int) -> str:
    """Schema listing restricted to ``count`` bound, case-insensitive names."""
    binds = ", ".join("?" for _ in range(count))
    return f"""
    SELECT s.name
    FROM sys.schemas s
    WHERE s.name NOT IN (
        'sys', 'INFORMATION_SCHEMA', 'guest', 'db_owner', 'db_accessadmin',
        'db_securityadmin', 'db_ddladmin', 'db_backupoperator', 'db_datareader',
        'db_datawriter', 'db_denydatareader', 'db_denydatawriter'
    )
      AND LOWER(s.name) IN ({binds})
    ORDER BY s.name
"""

TABLES_SQL = """
    SELECT table_name
    FROM INFORMATION_SCHEMA.TABLES
    WHERE table_schema = ? AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

COLUMNS_SQL = """
    SELECT
        column_name,
        data_type,
        character_maximum_length,
        numeric_precision,
        numeric_scale,
        is_nullable,
        ordinal_position,
        column_default,
        COLUMNPROPERTY(OBJECT_ID(table_schema + '.' + table_name), column_name, 'IsIdentity')
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE table_schema = ? AND table_name = ?
    ORDER BY ordinal_position
"""

KEY_CONSTRAINTS_SQL = """
    SELECT tc.constraint_name, tc.constraint_type, kcu.column_name, kcu.ordinal_position
    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
      ON kcu.constraint_name = tc.constraint_name
     AND kcu.table_schema = tc.table_schema
     AND kcu.table_name = tc.table_name
    WHERE tc.table_schema = ? AND tc.table_name = ?
      AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
    ORDER BY tc.constraint_name, kcu.ordinal_position
"""

FK_SQL = """
    SELECT
        fk.name,
        OBJECT_SCHEMA_NAME(fkc.referenced_object_id),
        OBJECT_NAME(fkc.referenced_object_id),
        COL_NAME(fkc.parent_object_id, fkc.parent_column_id),
        COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id)
    FROM sys.foreign_keys fk
    JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
    WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = ?
      AND OBJECT_NAME(fk.parent_object_id) = ?
    ORDER BY fk.name, fkc.constraint_column_id
"""

INDEXES_SQL = """
    SELECT i.name, i.is_unique, i.is_primary_key, c.name AS column_name, ic.key_ordinal
    FROM sys.indexes i
    JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    WHERE i.object_id = OBJECT_ID(? + '.' + ?)
      AND i.name IS NOT NULL
    ORDER BY i.name, ic.key_ordinal
"""


class SQLServerMetadataCollector:
    """Collects SQL Server structural metadata into canonical models."""

    def __init__(
        self, fetch: Fetch, normalizer: TypeNormalizer, db_type: DatabaseType
    ) -> None:
        self._fetch = fetch
        self._normalizer = normalizer
        self._db_type = db_type

    async def get_schemas(self, names: list[str] | None = None) -> list[SchemaModel]:
        wanted = schema_name_filter(names)
        if wanted is None:
            result = await self._fetch(SCHEMAS_SQL, None)
        elif not wanted:
            return []
        else:
            result = await self._fetch(schemas_filtered_sql(len(wanted)), tuple(wanted))
        return [SchemaModel(name=row[0]) for row in result.rows]

    async def get_tables(self, schema: str) -> list[TableModel]:
        result = await self._fetch(TABLES_SQL, (schema,))
        return [TableModel(schema_name=schema, name=row[0]) for row in result.rows]

    async def get_columns(self, schema: str, table: str) -> list[ColumnModel]:
        result = await self._fetch(COLUMNS_SQL, (schema, table))
        return [self._map_column(row) for row in result.rows]

    async def get_constraints(self, schema: str, table: str) -> list[ConstraintModel]:
        keys = await self._fetch(KEY_CONSTRAINTS_SQL, (schema, table))
        by_name: dict[str, dict] = {}
        for name, ctype, column, _pos in keys.rows:
            entry = by_name.setdefault(name, {"type": ctype, "columns": []})
            if column:
                entry["columns"].append(column)
        constraints = [
            ConstraintModel(
                name=name,
                constraint_type=(
                    ConstraintType.PRIMARY_KEY
                    if str(entry["type"]).upper() == "PRIMARY KEY"
                    else ConstraintType.UNIQUE
                ),
                columns=entry["columns"],
            )
            for name, entry in by_name.items()
        ]

        fks = await self._fetch(FK_SQL, (schema, table))
        fk_by_name: dict[str, dict] = {}
        for name, ref_schema, ref_table, column, ref_column in fks.rows:
            entry = fk_by_name.setdefault(
                name, {"ref_schema": ref_schema, "ref_table": ref_table, "cols": [], "refs": []}
            )
            if column:
                entry["cols"].append(column)
            if ref_column:
                entry["refs"].append(ref_column)
        for name, entry in fk_by_name.items():
            constraints.append(
                ConstraintModel(
                    name=name,
                    constraint_type=ConstraintType.FOREIGN_KEY,
                    columns=entry["cols"],
                    references=ForeignKeyReference(
                        ref_schema=entry["ref_schema"],
                        ref_table=entry["ref_table"],
                        ref_columns=entry["refs"],
                    ),
                )
            )
        return constraints

    async def get_indexes(self, schema: str, table: str) -> list[IndexModel]:
        result = await self._fetch(INDEXES_SQL, (schema, table))
        by_index: dict[str, dict] = {}
        for name, is_unique, is_primary, column, _ordinal in result.rows:
            entry = by_index.setdefault(
                name, {"unique": bool(is_unique), "primary": bool(is_primary), "cols": []}
            )
            if column:
                entry["cols"].append(IndexColumn(name=column))
        return [
            IndexModel(
                name=name,
                columns=entry["cols"],
                unique=entry["unique"],
                primary=entry["primary"],
            )
            for name, entry in by_index.items()
        ]

    def _map_column(self, row: tuple) -> ColumnModel:
        (
            name,
            data_type,
            char_length,
            numeric_precision,
            numeric_scale,
            is_nullable,
            ordinal_position,
            column_default,
            is_identity,
        ) = row
        length = int(char_length) if char_length not in (None, -1) else None
        precision = int(numeric_precision) if numeric_precision is not None else None
        scale = int(numeric_scale) if numeric_scale is not None else None
        normalized = self._normalizer.normalize(data_type, length, precision, scale)
        identity = bool(is_identity)
        ident = normalize_identifier(name, self._db_type)
        return ColumnModel(
            name=name,
            ordinal_position=int(ordinal_position),
            logical_type=normalized.logical_type,
            native_type=_render_native_type(data_type, length, precision, scale),
            length=normalized.length,
            precision=normalized.precision,
            scale=normalized.scale,
            nullable=str(is_nullable).upper() == "YES",
            default_expression=column_default if column_default else None,
            is_identity=identity,
            generated_strategy=(
                GeneratedValueStrategy.IDENTITY if identity else GeneratedValueStrategy.NONE
            ),
            quoted=ident.quoted,
        )


def _render_native_type(
    data_type: str, length: int | None, precision: int | None, scale: int | None
) -> str:
    base = str(data_type).upper()
    if length and base in {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR"}:
        return f"{base}({length})"
    if precision is not None and base in {"DECIMAL", "NUMERIC"}:
        return f"{base}({precision},{scale or 0})" if scale else f"{base}({precision})"
    return base
