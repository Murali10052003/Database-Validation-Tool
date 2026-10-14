"""Oracle metadata collection.

SQL against the ``ALL_*`` data-dictionary views, plus mapping of result rows into
canonical models. All Oracle-specific SQL is confined to this module.
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

# Oracle-maintained schemas that are never migration targets.
_SYSTEM_SCHEMAS = (
    "SYS", "SYSTEM", "SYSAUX", "OUTLN", "DBSNMP", "APPQOSSYS", "CTXSYS", "XDB",
    "ANONYMOUS", "MDSYS", "ORDSYS", "ORDDATA", "OLAPSYS", "WMSYS", "LBACSYS",
    "GSMADMIN_INTERNAL", "AUDSYS", "DVSYS", "DVF", "REMOTE_SCHEDULER_AGENT",
    "SYS$UMF", "GGSYS", "OJVMSYS", "DBSFWUSER", "SYSBACKUP", "SYSDG", "SYSKM",
    "SYSRAC", "PDBADMIN", "FLOWS_FILES", "APEX_PUBLIC_USER",
)

SCHEMAS_SQL = f"""
    SELECT username
    FROM all_users
    WHERE username NOT IN ({",".join(f"'{s}'" for s in _SYSTEM_SCHEMAS)})
    ORDER BY username
"""


def schemas_filtered_sql(count: int) -> str:
    """Schema listing restricted to ``count`` bound, case-insensitive names."""
    binds = ", ".join(f":s{i}" for i in range(count))
    return f"""
    SELECT username
    FROM all_users
    WHERE username NOT IN ({",".join(f"'{s}'" for s in _SYSTEM_SCHEMAS)})
      AND LOWER(username) IN ({binds})
    ORDER BY username
"""

TABLES_SQL = """
    SELECT table_name
    FROM all_tables
    WHERE owner = :owner
    ORDER BY table_name
"""

COLUMNS_SQL = """
    SELECT
        column_name,
        data_type,
        data_length,
        data_precision,
        data_scale,
        nullable,
        column_id,
        data_default,
        char_length,
        virtual_column,
        identity_column
    FROM all_tab_cols
    WHERE owner = :owner
      AND table_name = :table_name
      AND hidden_column = 'NO'
    ORDER BY column_id
"""

CONSTRAINTS_SQL = """
    SELECT
        c.constraint_name,
        c.constraint_type,
        c.search_condition,
        rc.owner AS ref_owner,
        rc.table_name AS ref_table,
        rc.constraint_name AS ref_constraint,
        c.delete_rule
    FROM all_constraints c
    LEFT JOIN all_constraints rc
      ON rc.owner = c.r_owner
     AND rc.constraint_name = c.r_constraint_name
    WHERE c.owner = :owner
      AND c.table_name = :table_name
      AND c.constraint_type IN ('P', 'R', 'U', 'C')
    ORDER BY c.constraint_name
"""

# Columns of this table's own constraints plus those of the constraints its foreign
# keys reference; never the whole owner's constraint columns.
CONS_COLUMNS_SQL = """
    SELECT cc.owner, cc.constraint_name, cc.column_name, cc.position
    FROM all_cons_columns cc
    WHERE (cc.owner = :owner AND cc.table_name = :table_name)
       OR (cc.owner, cc.constraint_name) IN (
            SELECT fk.r_owner, fk.r_constraint_name
            FROM all_constraints fk
            WHERE fk.owner = :owner
              AND fk.table_name = :table_name
              AND fk.constraint_type = 'R'
       )
    ORDER BY cc.owner, cc.constraint_name, cc.position
"""

INDEXES_SQL = """
    SELECT index_name, uniqueness, index_type
    FROM all_indexes
    WHERE table_owner = :owner
      AND table_name = :table_name
    ORDER BY index_name
"""

IND_COLUMNS_SQL = """
    SELECT index_name, column_name, descend
    FROM all_ind_columns
    WHERE table_owner = :owner
      AND table_name = :table_name
    ORDER BY index_name, column_position
"""

SEQUENCES_SQL = """
    SELECT sequence_name, min_value, max_value, increment_by, cycle_flag, last_number
    FROM all_sequences
    WHERE sequence_owner = :owner
    ORDER BY sequence_name
"""

VIEWS_SQL = """
    SELECT view_name AS name, 'N' AS materialized FROM all_views WHERE owner = :owner
    UNION ALL
    SELECT mview_name AS name, 'Y' AS materialized FROM all_mviews WHERE owner = :owner
    ORDER BY name
"""

ROUTINES_SQL = """
    SELECT object_name, object_type
    FROM all_objects
    WHERE owner = :owner
      AND object_type IN ('PROCEDURE', 'FUNCTION')
    ORDER BY object_name
"""

TRIGGERS_SQL = """
    SELECT trigger_name, table_name, trigger_type, triggering_event, status
    FROM all_triggers
    WHERE table_owner = :owner
    ORDER BY table_name, trigger_name
"""

PART_TABLES_SQL = """
    SELECT table_name, partitioning_type
    FROM all_part_tables
    WHERE owner = :owner
"""

PARTITIONS_SQL = """
    SELECT table_name, partition_name
    FROM all_tab_partitions
    WHERE table_owner = :owner
    ORDER BY table_name, partition_position
"""

_ORACLE_CONSTRAINT_TYPES = {
    "P": ConstraintType.PRIMARY_KEY,
    "R": ConstraintType.FOREIGN_KEY,
    "U": ConstraintType.UNIQUE,
    "C": ConstraintType.CHECK,
}


class OracleMetadataCollector:
    """Collects Oracle structural metadata into canonical models."""

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
        result = await self._fetch(TABLES_SQL, {"owner": schema})
        return [TableModel(schema_name=schema, name=row[0]) for row in result.rows]

    async def get_columns(self, schema: str, table: str) -> list[ColumnModel]:
        result = await self._fetch(COLUMNS_SQL, {"owner": schema, "table_name": table})
        columns: list[ColumnModel] = []
        for row in result.rows:
            columns.append(self._map_column(row))
        return columns

    async def get_constraints(self, schema: str, table: str) -> list[ConstraintModel]:
        cons = await self._fetch(CONSTRAINTS_SQL, {"owner": schema, "table_name": table})
        # Columns of this table's constraints and of any constraint its FKs reference.
        cols = await self._fetch(
            CONS_COLUMNS_SQL, {"owner": schema, "table_name": table}
        )
        by_constraint: dict[tuple[str, str], list[str]] = {}
        for owner, cname, col_name, _pos in cols.rows:
            by_constraint.setdefault((owner, cname), []).append(col_name)

        constraints: list[ConstraintModel] = []
        for row in cons.rows:
            name, ctype_code, search, ref_owner, ref_table, ref_constraint, delete_rule = row
            ctype = _ORACLE_CONSTRAINT_TYPES.get(ctype_code)
            if ctype is None:
                continue
            references = None
            if ctype is ConstraintType.FOREIGN_KEY and ref_table:
                references = ForeignKeyReference(
                    ref_schema=ref_owner,
                    ref_table=ref_table,
                    ref_columns=by_constraint.get((ref_owner, ref_constraint), []),
                    on_delete=(delete_rule or None),
                )
            constraints.append(
                ConstraintModel(
                    name=name,
                    constraint_type=ctype,
                    columns=by_constraint.get((schema, name), []),
                    check_expression=(
                        _clean_default(search) if ctype is ConstraintType.CHECK else None
                    ),
                    references=references,
                )
            )
        return constraints

    async def get_indexes(self, schema: str, table: str) -> list[IndexModel]:
        idx = await self._fetch(INDEXES_SQL, {"owner": schema, "table_name": table})
        cols = await self._fetch(IND_COLUMNS_SQL, {"owner": schema, "table_name": table})
        by_index: dict[str, list[IndexColumn]] = {}
        for iname, col_name, descend in cols.rows:
            by_index.setdefault(iname, []).append(
                IndexColumn(name=col_name, descending=str(descend).upper() == "DESC")
            )
        indexes: list[IndexModel] = []
        for name, uniqueness, index_type in idx.rows:
            indexes.append(
                IndexModel(
                    name=name,
                    columns=by_index.get(name, []),
                    unique=str(uniqueness).upper() == "UNIQUE",
                    index_type=index_type,
                )
            )
        return indexes

    async def get_sequences(self, schema: str) -> list[SequenceModel]:
        result = await self._fetch(SEQUENCES_SQL, {"owner": schema})
        sequences: list[SequenceModel] = []
        for name, min_value, max_value, increment, cycle, last_number in result.rows:
            sequences.append(
                SequenceModel(
                    name=name,
                    strategy=GeneratedValueStrategy.SEQUENCE,
                    increment=_as_int(increment),
                    min_value=_as_int(min_value),
                    max_value=_as_int(max_value),
                    current_value=_as_int(last_number),
                    cycle=str(cycle).upper() in {"Y", "YES"},
                )
            )
        return sequences

    async def get_views(self, schema: str) -> list[ViewModel]:
        result = await self._fetch(VIEWS_SQL, {"owner": schema})
        return [
            ViewModel(name=row[0], materialized=str(row[1]).upper() == "Y")
            for row in result.rows
        ]

    async def get_routines(self, schema: str) -> list[RoutineModel]:
        result = await self._fetch(ROUTINES_SQL, {"owner": schema})
        routines: list[RoutineModel] = []
        for name, object_type in result.rows:
            rtype = (
                RoutineType.PROCEDURE
                if str(object_type).upper() == "PROCEDURE"
                else RoutineType.FUNCTION
            )
            routines.append(RoutineModel(name=name, routine_type=rtype, language="PLSQL"))
        return routines

    async def get_triggers(self, schema: str) -> list[TriggerModel]:
        result = await self._fetch(TRIGGERS_SQL, {"owner": schema})
        triggers: list[TriggerModel] = []
        for name, table, trigger_type, event, status in result.rows:
            triggers.append(
                TriggerModel(
                    name=name,
                    table=table,
                    timing=_trigger_timing(trigger_type),
                    events=_trigger_events(event),
                    enabled=str(status).upper() == "ENABLED",
                )
            )
        return triggers

    async def get_partitions(self, schema: str) -> list[PartitionModel]:
        strategies = await self._fetch(PART_TABLES_SQL, {"owner": schema})
        strategy_by_table = {row[0]: row[1] for row in strategies.rows}
        result = await self._fetch(PARTITIONS_SQL, {"owner": schema})
        partitions: list[PartitionModel] = []
        for table_name, partition_name in result.rows:
            partitions.append(
                PartitionModel(
                    name=partition_name,
                    table=table_name,
                    strategy=(
                        str(strategy_by_table[table_name]).upper()
                        if table_name in strategy_by_table
                        else None
                    ),
                )
            )
        return partitions

    def _map_column(self, row: tuple) -> ColumnModel:
        (
            name,
            data_type,
            data_length,
            data_precision,
            data_scale,
            nullable,
            column_id,
            data_default,
            char_length,
            virtual_column,
            identity_column,
        ) = row
        length = int(char_length) if char_length else (int(data_length) if data_length else None)
        precision = int(data_precision) if data_precision is not None else None
        scale = int(data_scale) if data_scale is not None else None
        normalized = self._normalizer.normalize(data_type, length, precision, scale)
        is_identity = str(identity_column).upper() == "YES"
        is_generated = str(virtual_column).upper() == "YES"
        ident = normalize_identifier(name, DatabaseType.ORACLE)
        return ColumnModel(
            name=name,
            ordinal_position=int(column_id),
            logical_type=normalized.logical_type,
            native_type=_render_native_type(data_type, length, precision, scale),
            length=normalized.length,
            precision=normalized.precision,
            scale=normalized.scale,
            nullable=str(nullable).upper() == "Y",
            default_expression=_clean_default(data_default),
            is_identity=is_identity,
            is_generated=is_generated,
            generated_strategy=(
                GeneratedValueStrategy.IDENTITY if is_identity else GeneratedValueStrategy.NONE
            ),
            quoted=ident.quoted,
        )


def _render_native_type(
    data_type: str, length: int | None, precision: int | None, scale: int | None
) -> str:
    """Reconstruct a readable native type such as ``VARCHAR2(200)`` or ``NUMBER(10,2)``."""
    base = data_type.upper()
    if base in {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "RAW"} and length:
        return f"{base}({length})"
    if base in {"NUMBER", "DECIMAL", "NUMERIC"} and precision is not None:
        return f"{base}({precision},{scale or 0})" if scale else f"{base}({precision})"
    return base


def _clean_default(value: object) -> str | None:
    """Trim Oracle's DATA_DEFAULT (a LONG) which often carries trailing whitespace."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: object) -> int | None:
    """Best-effort integer conversion for sequence bounds (Oracle returns Decimals)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _trigger_timing(trigger_type: object) -> str | None:
    """Map Oracle's TRIGGER_TYPE (e.g. 'BEFORE EACH ROW') to a timing keyword."""
    text = str(trigger_type or "").upper()
    if "INSTEAD OF" in text:
        return "INSTEAD OF"
    if text.startswith("BEFORE"):
        return "BEFORE"
    if text.startswith("AFTER"):
        return "AFTER"
    return None


def _trigger_events(event: object) -> list[str]:
    """Split Oracle's TRIGGERING_EVENT (e.g. 'INSERT OR UPDATE') into canonical events."""
    text = str(event or "").upper()
    return [e.strip() for e in text.split(" OR ") if e.strip()]
