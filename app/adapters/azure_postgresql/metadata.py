"""PostgreSQL metadata collection via ``information_schema``.

All PostgreSQL-specific SQL is confined to this module. Row results are mapped to
canonical models identical to those produced by every other adapter.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.adapters._helpers import schema_name_filter
from app.core.enums import DatabaseType, GeneratedValueStrategy
from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel, ConstraintType, ForeignKeyReference
from app.models.database import QueryResult
from app.models.index import IndexColumn, IndexModel
from app.models.partition import PartitionModel
from app.models.routine import RoutineModel, RoutineType
from app.models.schema import SchemaModel
from app.models.sequence import SequenceModel
from app.models.table import TableModel
from app.models.trigger import TriggerModel
from app.models.view import ViewModel
from app.normalization.datatypes import TypeNormalizer
from app.normalization.identifiers import normalize_identifier

Fetch = Callable[[str, dict | None], Awaitable[QueryResult]]

SCHEMAS_SQL = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
      AND schema_name NOT LIKE 'pg_%%'
    ORDER BY schema_name
"""


def schemas_filtered_sql(count: int) -> str:
    """Schema listing restricted to ``count`` bound, case-insensitive names."""
    binds = ", ".join(f"%(s{i})s" for i in range(count))
    return f"""
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
      AND schema_name NOT LIKE 'pg_%%'
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
        is_identity,
        is_generated,
        udt_name
    FROM information_schema.columns
    WHERE table_schema = %(schema)s
      AND table_name = %(table)s
    ORDER BY ordinal_position
"""

CONSTRAINTS_SQL = """
    SELECT
        con.conname,
        con.contype,
        pg_get_constraintdef(con.oid) AS definition,
        (
            SELECT array_agg(a.attname ORDER BY k.ord)
            FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
        ) AS columns,
        rns.nspname AS ref_schema,
        rel2.relname AS ref_table,
        (
            SELECT array_agg(a.attname ORDER BY k.ord)
            FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum
        ) AS ref_columns,
        con.confdeltype,
        con.confupdtype
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
    LEFT JOIN pg_class rel2 ON rel2.oid = con.confrelid
    LEFT JOIN pg_namespace rns ON rns.oid = rel2.relnamespace
    WHERE ns.nspname = %(schema)s
      AND rel.relname = %(table)s
      AND con.contype IN ('p', 'f', 'u', 'c')
    ORDER BY con.conname
"""

INDEXES_SQL = """
    SELECT
        i.relname AS index_name,
        idx.indisunique AS is_unique,
        idx.indisprimary AS is_primary,
        am.amname AS index_type,
        (
            -- pg_get_indexdef column numbering is 1-based; generate_subscripts over
            -- the 0-based int2vector indkey yields 0..n-1, so shift by one.
            SELECT array_agg(pg_get_indexdef(idx.indexrelid, (k.ord + 1)::int, true) ORDER BY k.ord)
            FROM generate_subscripts(idx.indkey, 1) AS k(ord)
        ) AS columns
    FROM pg_index idx
    JOIN pg_class i ON i.oid = idx.indexrelid
    JOIN pg_class t ON t.oid = idx.indrelid
    JOIN pg_namespace ns ON ns.oid = t.relnamespace
    JOIN pg_am am ON am.oid = i.relam
    WHERE ns.nspname = %(schema)s
      AND t.relname = %(table)s
    ORDER BY i.relname
"""

SEQUENCES_SQL = """
    SELECT
        sequence_name,
        start_value,
        increment,
        minimum_value,
        maximum_value,
        cycle_option
    FROM information_schema.sequences
    WHERE sequence_schema = %(schema)s
    ORDER BY sequence_name
"""

VIEWS_SQL = """
    SELECT table_name AS name, false AS materialized
    FROM information_schema.views
    WHERE table_schema = %(schema)s
    UNION ALL
    SELECT matviewname AS name, true AS materialized
    FROM pg_matviews
    WHERE schemaname = %(schema)s
    ORDER BY name
"""

ROUTINES_SQL = """
    SELECT routine_name, routine_type, data_type, external_language
    FROM information_schema.routines
    WHERE routine_schema = %(schema)s
      AND routine_type IN ('FUNCTION', 'PROCEDURE')
    ORDER BY routine_name
"""

TRIGGERS_SQL = """
    SELECT trigger_name, event_object_table, action_timing, event_manipulation
    FROM information_schema.triggers
    WHERE trigger_schema = %(schema)s
    ORDER BY event_object_table, trigger_name
"""

PARTITIONS_SQL = """
    SELECT
        parent.relname AS table_name,
        child.relname AS partition_name,
        pg_get_partkeydef(parent.oid) AS strategy_key,
        pg_get_expr(child.relpartbound, child.oid) AS bound
    FROM pg_inherits i
    JOIN pg_class child ON child.oid = i.inhrelid
    JOIN pg_class parent ON parent.oid = i.inhparent
    JOIN pg_namespace ns ON ns.oid = parent.relnamespace
    WHERE ns.nspname = %(schema)s
    ORDER BY parent.relname, child.relname
"""


class PostgreSQLMetadataCollector:
    """Collects PostgreSQL structural metadata into canonical models."""

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
        return [self._map_constraint(row) for row in result.rows]

    async def get_indexes(self, schema: str, table: str) -> list[IndexModel]:
        result = await self._fetch(INDEXES_SQL, {"schema": schema, "table": table})
        return [self._map_index(row) for row in result.rows]

    async def get_sequences(self, schema: str) -> list[SequenceModel]:
        result = await self._fetch(SEQUENCES_SQL, {"schema": schema})
        return [self._map_sequence(row) for row in result.rows]

    async def get_views(self, schema: str) -> list[ViewModel]:
        result = await self._fetch(VIEWS_SQL, {"schema": schema})
        return [ViewModel(name=row[0], materialized=bool(row[1])) for row in result.rows]

    async def get_routines(self, schema: str) -> list[RoutineModel]:
        result = await self._fetch(ROUTINES_SQL, {"schema": schema})
        routines: list[RoutineModel] = []
        for name, routine_type, return_type, language in result.rows:
            rtype = (
                RoutineType.PROCEDURE
                if str(routine_type).upper() == "PROCEDURE"
                else RoutineType.FUNCTION
            )
            routines.append(
                RoutineModel(
                    name=name,
                    routine_type=rtype,
                    return_type=return_type or None,
                    language=language or None,
                )
            )
        return routines

    async def get_triggers(self, schema: str) -> list[TriggerModel]:
        result = await self._fetch(TRIGGERS_SQL, {"schema": schema})
        # information_schema yields one row per firing event; collapse by (name, table).
        by_key: dict[tuple[str, str], TriggerModel] = {}
        for name, table, timing, event in result.rows:
            key = (name, table)
            trigger = by_key.get(key)
            if trigger is None:
                by_key[key] = TriggerModel(
                    name=name, table=table, timing=timing, events=[event] if event else []
                )
            elif event and event not in trigger.events:
                trigger.events.append(event)
        return list(by_key.values())

    async def get_partitions(self, schema: str) -> list[PartitionModel]:
        result = await self._fetch(PARTITIONS_SQL, {"schema": schema})
        partitions: list[PartitionModel] = []
        for table_name, partition_name, strategy_key, bound in result.rows:
            partitions.append(
                PartitionModel(
                    name=partition_name,
                    table=table_name,
                    strategy=_partition_strategy(strategy_key),
                    bound=bound or None,
                )
            )
        return partitions

    def _map_constraint(self, row: tuple) -> ConstraintModel:
        name, contype, definition, columns, ref_schema, ref_table, ref_columns, on_del, on_upd = row
        ctype = _PG_CONSTRAINT_TYPES[contype]
        references = None
        if ctype is ConstraintType.FOREIGN_KEY and ref_table:
            references = ForeignKeyReference(
                ref_schema=ref_schema,
                ref_table=ref_table,
                ref_columns=list(ref_columns or []),
                on_delete=_PG_FK_ACTIONS.get(on_del),
                on_update=_PG_FK_ACTIONS.get(on_upd),
            )
        return ConstraintModel(
            name=name,
            constraint_type=ctype,
            columns=list(columns or []),
            check_expression=definition if ctype is ConstraintType.CHECK else None,
            references=references,
        )

    def _map_index(self, row: tuple) -> IndexModel:
        name, is_unique, is_primary, index_type, columns = row
        return IndexModel(
            name=name,
            columns=[IndexColumn(name=str(c)) for c in (columns or [])],
            unique=bool(is_unique),
            primary=bool(is_primary),
            index_type=index_type,
        )

    def _map_sequence(self, row: tuple) -> SequenceModel:
        name, start, increment, min_value, max_value, cycle = row
        return SequenceModel(
            name=name,
            strategy=GeneratedValueStrategy.SEQUENCE,
            start_value=_as_int(start),
            increment=_as_int(increment),
            min_value=_as_int(min_value),
            max_value=_as_int(max_value),
            cycle=str(cycle).upper() == "YES",
        )

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
            is_generated,
            udt_name,
        ) = row
        length = int(char_length) if char_length is not None else None
        # PostgreSQL reports numeric_precision for integer types in bits (radix 2),
        # which the shared numeric normalizer would misread as decimal digits and
        # collapse INTEGER to DECIMAL; only forward precision/scale for the
        # arbitrary-precision numeric/decimal family.
        if data_type.upper() in {"NUMERIC", "DECIMAL"}:
            precision = int(numeric_precision) if numeric_precision is not None else None
            scale = int(numeric_scale) if numeric_scale is not None else None
        else:
            precision = scale = None
        normalized = self._normalizer.normalize(data_type, length, precision, scale)
        identity = str(is_identity).upper() == "YES"
        generated = str(is_generated).upper() == "ALWAYS"
        default = column_default if column_default else None
        strategy = GeneratedValueStrategy.NONE
        if identity:
            strategy = GeneratedValueStrategy.IDENTITY
        elif default and default.lower().startswith("nextval("):
            strategy = GeneratedValueStrategy.SEQUENCE
        ident = normalize_identifier(name, DatabaseType.AZURE_POSTGRESQL)
        return ColumnModel(
            name=name,
            ordinal_position=int(ordinal_position),
            logical_type=normalized.logical_type,
            native_type=(
                f"{data_type.upper()} ({udt_name})"
                if data_type.upper() in {"ARRAY", "USER-DEFINED"}
                else _render_native_type(data_type, length, precision, scale)
            ),
            length=normalized.length,
            precision=normalized.precision,
            scale=normalized.scale,
            nullable=str(is_nullable).upper() == "YES",
            default_expression=default,
            is_identity=identity,
            is_generated=generated,
            generated_strategy=strategy,
            quoted=ident.quoted,
            extra={"udt_name": str(udt_name)} if udt_name else {},
        )


def _render_native_type(
    data_type: str, length: int | None, precision: int | None, scale: int | None
) -> str:
    """Reconstruct a readable native type such as ``CHARACTER VARYING(100)``."""
    base = data_type.upper()
    if length and base in {"CHARACTER VARYING", "VARCHAR", "CHARACTER", "CHAR"}:
        return f"{base}({length})"
    if precision is not None and base in {"NUMERIC", "DECIMAL"}:
        return f"{base}({precision},{scale or 0})" if scale else f"{base}({precision})"
    return base


_PG_CONSTRAINT_TYPES = {
    "p": ConstraintType.PRIMARY_KEY,
    "f": ConstraintType.FOREIGN_KEY,
    "u": ConstraintType.UNIQUE,
    "c": ConstraintType.CHECK,
}

# pg_constraint.confdeltype / confupdtype codes to canonical referential actions.
_PG_FK_ACTIONS = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


def _as_int(value: object) -> int | None:
    """Best-effort integer conversion for sequence bounds (which may be strings)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _partition_strategy(partkeydef: object) -> str | None:
    """Extract the strategy word (RANGE/LIST/HASH) from ``pg_get_partkeydef`` output."""
    if not partkeydef:
        return None
    return str(partkeydef).split("(", 1)[0].strip().upper() or None
