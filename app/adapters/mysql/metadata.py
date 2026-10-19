"""MySQL metadata collection via ``information_schema``.

All MySQL-specific SQL is confined to this module. MySQL has no sequences (it uses
``AUTO_INCREMENT``), so ``get_sequences`` returns nothing.
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

Fetch = Callable[[str, dict | None], Awaitable[QueryResult]]

SCHEMAS_SQL = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
    ORDER BY schema_name
"""


def schemas_filtered_sql(count: int) -> str:
    """Schema listing restricted to ``count`` bound, case-insensitive names."""
    binds = ", ".join(f"%(s{i})s" for i in range(count))
    return f"""
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
      AND LOWER(schema_name) IN ({binds})
    ORDER BY schema_name
"""

TABLES_SQL = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = %(schema)s
      AND table_type = 'BASE TABLE'
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
        extra,
        column_type
    FROM information_schema.columns
    WHERE table_schema = %(schema)s
      AND table_name = %(table)s
    ORDER BY ordinal_position
"""

CONSTRAINTS_SQL = """
    SELECT
        tc.constraint_name,
        tc.constraint_type,
        kcu.column_name,
        kcu.referenced_table_schema,
        kcu.referenced_table_name,
        kcu.referenced_column_name,
        kcu.ordinal_position
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_schema = tc.constraint_schema
     AND kcu.constraint_name = tc.constraint_name
     AND kcu.table_name = tc.table_name
    WHERE tc.table_schema = %(schema)s
      AND tc.table_name = %(table)s
    ORDER BY tc.constraint_name, kcu.ordinal_position
"""

INDEXES_SQL = """
    SELECT index_name, non_unique, column_name, seq_in_index, index_type
    FROM information_schema.statistics
    WHERE table_schema = %(schema)s
      AND table_name = %(table)s
    ORDER BY index_name, seq_in_index
"""

_MYSQL_CONSTRAINT_TYPES = {
    "PRIMARY KEY": ConstraintType.PRIMARY_KEY,
    "FOREIGN KEY": ConstraintType.FOREIGN_KEY,
    "UNIQUE": ConstraintType.UNIQUE,
    "CHECK": ConstraintType.CHECK,
}


class MySQLMetadataCollector:
    """Collects MySQL structural metadata into canonical models."""

    def __init__(self, fetch: Fetch, normalizer: TypeNormalizer) -> None:
        self._fetch = fetch
        self._normalizer = normalizer

    async def get_schemas(self, names: list[str] | None = None) -> list[SchemaModel]:
        wanted = schema_name_filter(names)
        if wanted is None:
            result = await self._fetch(SCHEMAS_SQL, None)
        elif not wanted:
            return []
        else:
            result = await self._fetch(
                schemas_filtered_sql(len(wanted)),
                {f"s{i}": name for i, name in enumerate(wanted)},
            )
        return [SchemaModel(name=row[0]) for row in result.rows]

    async def get_tables(self, schema: str) -> list[TableModel]:
        result = await self._fetch(TABLES_SQL, {"schema": schema})
        return [TableModel(schema_name=schema, name=row[0]) for row in result.rows]

    async def get_columns(self, schema: str, table: str) -> list[ColumnModel]:
        result = await self._fetch(COLUMNS_SQL, {"schema": schema, "table": table})
        return [self._map_column(row) for row in result.rows]

    async def get_constraints(self, schema: str, table: str) -> list[ConstraintModel]:
        result = await self._fetch(CONSTRAINTS_SQL, {"schema": schema, "table": table})
        by_name: dict[str, dict] = {}
        for name, ctype, column, ref_schema, ref_table, ref_column, _pos in result.rows:
            entry = by_name.setdefault(
                name,
                {"type": ctype, "columns": [], "ref_schema": ref_schema,
                 "ref_table": ref_table, "ref_columns": []},
            )
            if column:
                entry["columns"].append(column)
            if ref_column:
                entry["ref_columns"].append(ref_column)
        constraints: list[ConstraintModel] = []
        for name, entry in by_name.items():
            ctype = _MYSQL_CONSTRAINT_TYPES.get(str(entry["type"]).upper())
            if ctype is None:
                continue
            references = None
            if ctype is ConstraintType.FOREIGN_KEY and entry["ref_table"]:
                references = ForeignKeyReference(
                    ref_schema=entry["ref_schema"],
                    ref_table=entry["ref_table"],
                    ref_columns=entry["ref_columns"],
                )
            constraints.append(
                ConstraintModel(
                    name=name,
                    constraint_type=ctype,
                    columns=entry["columns"],
                    references=references,
                )
            )
        return constraints

    async def get_indexes(self, schema: str, table: str) -> list[IndexModel]:
        result = await self._fetch(INDEXES_SQL, {"schema": schema, "table": table})
        by_index: dict[str, dict] = {}
        for name, non_unique, column, _seq, index_type in result.rows:
            entry = by_index.setdefault(
                name, {"unique": str(non_unique) in ("0", "False"), "type": index_type, "cols": []}
            )
            if column:
                entry["cols"].append(IndexColumn(name=column))
        return [
            IndexModel(
                name=name,
                columns=entry["cols"],
                unique=entry["unique"],
                primary=name == "PRIMARY",
                index_type=entry["type"],
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
            extra,
            column_type,
        ) = row
        length = int(char_length) if char_length is not None else None
        precision = int(numeric_precision) if numeric_precision is not None else None
        scale = int(numeric_scale) if numeric_scale is not None else None
        normalized = self._normalizer.normalize(data_type, length, precision, scale)
        is_identity = "auto_increment" in str(extra or "").lower()
        ident = normalize_identifier(name, DatabaseType.MYSQL)
        return ColumnModel(
            name=name,
            ordinal_position=int(ordinal_position),
            logical_type=normalized.logical_type,
            native_type=str(column_type or data_type).upper(),
            length=normalized.length,
            precision=normalized.precision,
            scale=normalized.scale,
            nullable=str(is_nullable).upper() == "YES",
            default_expression=column_default if column_default else None,
            is_identity=is_identity,
            generated_strategy=(
                GeneratedValueStrategy.AUTO_INCREMENT
                if is_identity
                else GeneratedValueStrategy.NONE
            ),
            quoted=ident.quoted,
        )
