"""Structural metadata mapping for the Oracle and PostgreSQL collectors."""

from __future__ import annotations

import pytest

from app.adapters.azure_postgresql.metadata import PostgreSQLMetadataCollector
from app.adapters.azure_postgresql.type_mapping import get_normalizer as pg_normalizer
from app.adapters.oracle.metadata import OracleMetadataCollector
from app.adapters.oracle.type_mapping import get_normalizer as ora_normalizer
from app.comparison.schema_comparator import SchemaComparator
from app.core.config import MappingConfig
from app.core.enums import DatabaseType, LogicalType, ValidationStatus
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.constraint import ConstraintType
from app.models.database import QueryResult


def _pg() -> PostgreSQLMetadataCollector:
    return PostgreSQLMetadataCollector(fetch=None, normalizer=pg_normalizer())  # type: ignore[arg-type]


def test_pg_maps_primary_key_and_foreign_key() -> None:
    c = _pg()
    pk = c._map_constraint(("emp_pkey", "p", "PRIMARY KEY (id)", ["id"], None, None, None, " ", " "))
    assert pk.constraint_type is ConstraintType.PRIMARY_KEY
    assert pk.columns == ["id"]

    fk = c._map_constraint(
        ("emp_dept_fk", "f", "FOREIGN KEY (dept_id) REFERENCES dept(id)",
         ["dept_id"], "hr", "dept", ["id"], "c", "a")
    )
    assert fk.constraint_type is ConstraintType.FOREIGN_KEY
    assert fk.references is not None
    assert fk.references.ref_table == "dept"
    assert fk.references.ref_columns == ["id"]
    assert fk.references.on_delete == "CASCADE"


def test_pg_maps_index_and_sequence() -> None:
    c = _pg()
    idx = c._map_index(("emp_email_key", True, False, "btree", ["email"]))
    assert idx.unique is True
    assert [col.name for col in idx.columns] == ["email"]

    seq = c._map_sequence(("emp_id_seq", 1, 1, 1, 9999, "NO"))
    assert seq.increment == 1
    assert seq.max_value == 9999
    assert seq.cycle is False


async def test_oracle_groups_constraint_columns() -> None:
    async def fetch(sql: str, params: dict | None) -> QueryResult:
        if "all_cons_columns" in sql:
            return QueryResult(columns=["o", "c", "col", "pos"], rows=[("HR", "PK_EMP", "ID", 1)])
        if "all_constraints" in sql:
            return QueryResult(
                columns=["name", "type", "search", "ro", "rt", "rc", "dr"],
                rows=[("PK_EMP", "P", None, None, None, None, None)],
            )
        return QueryResult()

    collector = OracleMetadataCollector(fetch=fetch, normalizer=ora_normalizer())
    constraints = await collector.get_constraints("HR", "EMP")
    assert len(constraints) == 1
    assert constraints[0].constraint_type is ConstraintType.PRIMARY_KEY
    assert constraints[0].columns == ["ID"]


async def test_oracle_constraint_columns_are_table_scoped_and_resolve_fk_references() -> None:
    calls: list[tuple[str, dict | None]] = []

    async def fetch(sql: str, params: dict | None) -> QueryResult:
        calls.append((sql, params))
        if "all_cons_columns" in sql:
            return QueryResult(rows=[
                ("HR", "FK_EMP_DEPT", "DEPT_ID", 1),
                ("OTHER", "PK_DEPT", "ID", 1),
            ])
        return QueryResult(rows=[
            ("FK_EMP_DEPT", "R", None, "OTHER", "DEPT", "PK_DEPT", "CASCADE"),
        ])

    collector = OracleMetadataCollector(fetch=fetch, normalizer=ora_normalizer())
    (fk,) = await collector.get_constraints("HR", "EMP")
    assert fk.columns == ["DEPT_ID"]
    assert fk.references is not None
    assert fk.references.ref_schema == "OTHER"
    assert fk.references.ref_columns == ["ID"]
    cons_sql, cons_params = next(c for c in calls if "all_cons_columns" in c[0])
    assert cons_params == {"owner": "HR", "table_name": "EMP"}
    assert "table_name = :table_name" in cons_sql


@pytest.mark.parametrize(("collector_factory", "marker"), [
    (lambda fetch: OracleMetadataCollector(fetch=fetch, normalizer=ora_normalizer()), ":s0"),
    (lambda fetch: PostgreSQLMetadataCollector(fetch=fetch, normalizer=pg_normalizer()), "%(s0)s"),
])
async def test_schema_listing_filters_in_catalog_query_with_bound_names(collector_factory, marker) -> None:
    seen: list[tuple[str, dict | None]] = []

    async def fetch(sql: str, params: dict | None) -> QueryResult:
        seen.append((sql, params))
        return QueryResult(rows=[("MIGRATION_TEST",)])

    collector = collector_factory(fetch)
    schemas = await collector.get_schemas(["Migration_Test", " ", "migration_test", "Hr"])
    assert [s.name for s in schemas] == ["MIGRATION_TEST"]
    (sql, params), = seen
    assert "LOWER(" in sql and marker in sql
    assert params == {"s0": "migration_test", "s1": "hr"}

    seen.clear()
    assert await collector.get_schemas([]) == []
    assert await collector.get_schemas([" "]) == []
    assert seen == []  # nothing selected -> no catalog query at all

    await collector.get_schemas(None)
    assert seen[0][1] is None and "LOWER(" not in seen[0][0]


async def test_pg_triggers_collapse_multiple_events() -> None:
    async def fetch(sql: str, params: dict | None) -> QueryResult:
        return QueryResult(
            columns=["name", "table", "timing", "event"],
            rows=[
                ("trg_audit", "emp", "AFTER", "INSERT"),
                ("trg_audit", "emp", "AFTER", "UPDATE"),
            ],
        )

    collector = PostgreSQLMetadataCollector(fetch=fetch, normalizer=pg_normalizer())
    triggers = await collector.get_triggers("hr")
    assert len(triggers) == 1
    assert triggers[0].timing == "AFTER"
    assert set(triggers[0].events) == {"INSERT", "UPDATE"}


async def test_pg_views_map_materialized_flag() -> None:
    async def fetch(sql: str, params: dict | None) -> QueryResult:
        return QueryResult(columns=["name", "materialized"], rows=[("v_emp", False), ("mv_stats", True)])

    collector = PostgreSQLMetadataCollector(fetch=fetch, normalizer=pg_normalizer())
    views = await collector.get_views("hr")
    assert {v.name: v.materialized for v in views} == {"v_emp": False, "mv_stats": True}


def test_oracle_trigger_timing_and_events() -> None:
    from app.adapters.oracle.metadata import _trigger_events, _trigger_timing

    assert _trigger_timing("BEFORE EACH ROW") == "BEFORE"
    assert _trigger_timing("INSTEAD OF") == "INSTEAD OF"
    assert _trigger_events("INSERT OR UPDATE OR DELETE") == ["INSERT", "UPDATE", "DELETE"]


def test_pg_partition_strategy_parse() -> None:
    from app.adapters.azure_postgresql.metadata import _partition_strategy

    assert _partition_strategy("RANGE (created_at)") == "RANGE"
    assert _partition_strategy(None) is None


@pytest.mark.parametrize("native,udt", [("ARRAY", "_int4"), ("ARRAY", "_text"), ("USER-DEFINED", "StatusCode")])
def test_postgres_preserves_unsupported_type_names(native, udt) -> None:
    column = _pg()._map_column(("value", native, None, None, None, "YES", 1, None, "NO", "NEVER", udt))
    assert column.logical_type == LogicalType.UNKNOWN
    assert udt in column.native_type
    assert column.extra["udt_name"] == udt


@pytest.mark.parametrize("source_type,source_udt,target_type,target_udt", [
    ("ARRAY", "_int4", "ARRAY", "_text"),
    ("USER-DEFINED", "status_a", "USER-DEFINED", "status_b"),
    ("time without time zone", "time", "time with time zone", "timetz"),
])
def test_postgres_unsupported_types_cannot_produce_column_pass(source_type, source_udt, target_type, target_udt) -> None:
    collector = _pg()
    source = collector._map_column(("value", source_type, None, None, None, "YES", 1, None, "NO", "NEVER", source_udt))
    target = collector._map_column(("value", target_type, None, None, None, "YES", 1, None, "NO", "NEVER", target_udt))
    comparator = SchemaComparator(MappingResolver(MappingConfig()), DatabaseType.AZURE_POSTGRESQL,
                                  DatabaseType.AZURE_POSTGRESQL, DatabaseCapabilities())
    result = comparator._compare_column_pair(source, target, "public.t.value", "public.t.value")
    assert result.status == ValidationStatus.NOT_SUPPORTED


def test_postgres_numeric_metadata_preserves_precision() -> None:
    column = _pg()._map_column(("value", "numeric", None, 10, 0, "YES", 1, None, "NO", "NEVER", "numeric"))
    assert column.logical_type == LogicalType.DECIMAL
    assert column.precision == 10
    assert column.scale == 0


def test_postgres_integer_metadata_retains_integer_type() -> None:
    column = _pg()._map_column(("value", "integer", None, 32, 0, "YES", 1, None, "NO", "NEVER", "int4"))
    assert column.logical_type == LogicalType.INTEGER
    assert column.precision is None
