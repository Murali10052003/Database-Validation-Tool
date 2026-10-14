"""Schema-scoped Discover & match: filtering, names-only inventories and scope propagation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.oracle.metadata import OracleMetadataCollector
from app.adapters.oracle.type_mapping import get_normalizer as ora_normalizer
from app.api import routes
from app.core.catalog import Catalog
from app.core.config import MigrationConfig
from app.core.enums import DatabaseType
from app.core.exceptions import ConfigurationError
from app.discovery.database_discovery import DatabaseDiscovery
from app.discovery.scoped_discovery import needs_structural, refresh_scope
from app.models.column import ColumnModel
from app.models.database import DatabaseModel, QueryResult
from app.models.schema import SchemaModel
from app.models.table import TableModel
from tests.conftest import MockAdapter

SOURCE = {"type": "oracle", "host": "source", "username": "reader"}
TARGET = {"type": "azure_postgresql", "host": "target", "username": "reader"}


def _schema(name: str, tables=("T",)) -> SchemaModel:
    return SchemaModel(name=name, tables=[
        TableModel(schema_name=name, name=table, columns=[
            ColumnModel(name="ID", ordinal_position=1, native_type="INTEGER"),
        ]) for table in tables
    ])


def _spy(adapter: MockAdapter) -> MockAdapter:
    for method in ("get_schemas", "get_tables", "get_columns", "get_constraints",
                   "get_indexes", "get_sequences", "get_views", "get_routines",
                   "get_triggers", "get_partitions"):
        setattr(adapter, method, AsyncMock(wraps=getattr(adapter, method)))
    return adapter


# -- discovery ---------------------------------------------------------------------


async def test_discovery_only_walks_selected_schemas_and_names_only_skips_children():
    adapter = _spy(MockAdapter(DatabaseType.ORACLE, [_schema("HR"), _schema("SALES"), _schema("HR2")]))
    model = await DatabaseDiscovery(adapter).discover(
        ["hr"], include_columns=False, include_structural=False,
    )
    assert [s.name for s in model.schemas] == ["HR"]
    adapter.get_schemas.assert_awaited_once_with(["hr"])
    assert [c.args[0] for c in adapter.get_tables.await_args_list] == ["HR"]
    for untouched in ("get_columns", "get_constraints", "get_indexes", "get_sequences",
                      "get_views", "get_routines", "get_triggers", "get_partitions"):
        getattr(adapter, untouched).assert_not_awaited()


async def test_discovery_can_require_every_requested_schema():
    adapter = _spy(MockAdapter(DatabaseType.ORACLE, [_schema("HR")]))
    with pytest.raises(ConfigurationError, match="MISSING"):
        await DatabaseDiscovery(adapter).discover(
            ["HR", "MISSING"], include_columns=False, require_all_schemas=True,
        )
    adapter.get_tables.assert_not_awaited()
    lenient = await DatabaseDiscovery(adapter).discover(["HR", "MISSING"], include_columns=False)
    assert [s.name for s in lenient.schemas] == ["HR"]


async def test_scoped_discovery_query_counts_against_unscoped_baseline():
    """Query counts through the real Oracle collector: 3 schemas x 5 tables each."""
    calls: list[str] = []

    async def fetch(sql: str, params: dict | None) -> QueryResult:
        calls.append(sql)
        if "all_users" in sql:
            names = ["APP", "OTHER1", "OTHER2"]
            if params:
                names = [n for n in names if n.lower() in params.values()]
            return QueryResult(rows=[(n,) for n in names])
        if "all_tables" in sql:
            return QueryResult(rows=[(f"T{i}",) for i in range(5)])
        if "all_tab_cols" in sql:
            return QueryResult(rows=[("ID", "NUMBER", 22, 10, 0, "N", 1, None, None, "NO", "NO")])
        return QueryResult()

    class OracleBacked(MockAdapter):
        def __init__(self) -> None:
            super().__init__(DatabaseType.ORACLE, [])
            self.meta = OracleMetadataCollector(fetch=fetch, normalizer=ora_normalizer())

        async def get_schemas(self, names=None):
            return await self.meta.get_schemas(names)

        async def get_tables(self, schema):
            return await self.meta.get_tables(schema)

        async def get_columns(self, schema, table):
            return await self.meta.get_columns(schema, table)

        async def get_constraints(self, schema, table):
            return await self.meta.get_constraints(schema, table)

        async def get_indexes(self, schema, table):
            return await self.meta.get_indexes(schema, table)

        async def get_sequences(self, schema):
            return await self.meta.get_sequences(schema)

        async def get_views(self, schema):
            return await self.meta.get_views(schema)

        async def get_routines(self, schema):
            return await self.meta.get_routines(schema)

        async def get_triggers(self, schema):
            return await self.meta.get_triggers(schema)

        async def get_partitions(self, schema):
            return await self.meta.get_partitions(schema)

    legacy = await DatabaseDiscovery(OracleBacked()).discover(
        None, include_columns=True, include_structural=True)
    legacy_queries = len(calls)
    calls.clear()
    scoped = await DatabaseDiscovery(OracleBacked()).discover(
        ["app"], include_columns=False, include_structural=False, require_all_schemas=True)
    scoped_queries = len(calls)

    assert len(legacy.schemas) == 3 and [s.name for s in scoped.schemas] == ["APP"]
    assert scoped_queries == 2  # schema listing + one table listing
    assert legacy_queries > 20 * scoped_queries
    assert not any("all_cons_columns" in sql for sql in calls)


# -- check-aware refresh -----------------------------------------------------------


@pytest.mark.parametrize(("checks", "expected"), [
    (["row_count"], False),
    (["schema", "null_count", "custom_query"], False),
    (["aggregate"], True),  # aggregates skip key columns, which needs constraints
    (["schema", "constraints"], True),
    (["row_count", "checksum"], True),
    (["views"], True),
])
def test_needs_structural(checks, expected):
    assert needs_structural(checks) is expected


@pytest.mark.parametrize(("checks", "structural"), [(["row_count"], False), (["constraints"], True)])
async def test_refresh_only_reads_structure_for_checks_that_use_it(checks, structural):
    from app.models.view import ViewModel

    model = DatabaseModel(database_type="oracle", schemas=[_schema("HR")])
    model.schemas[0].views = [ViewModel(name="V", materialized=False)]
    adapter = AsyncMock()
    adapter.get_columns.return_value = [ColumnModel(name="ID", ordinal_position=1, native_type="N")]
    adapter.get_constraints.return_value = []
    adapter.get_indexes.return_value = []
    adapter.get_views.return_value = model.schemas[0].views
    adapter.get_triggers.return_value = []
    adapter.get_partitions.return_value = []
    await refresh_scope(adapter, model, checks)
    adapter.get_columns.assert_awaited_once()
    for method in (adapter.get_constraints, adapter.get_indexes, adapter.get_views,
                   adapter.get_triggers, adapter.get_partitions):
        assert method.await_count == (1 if structural else 0)


# -- catalog -----------------------------------------------------------------------


def test_names_only_inventory_is_distinguishable_and_not_refreshable(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    config = MigrationConfig(
        migration={"name": "x"}, source=SOURCE, target=TARGET,
    ).source
    model = DatabaseModel(database_type="oracle", schemas=[_schema("HR")])
    names_only = catalog.save_inventory(config, model, collected=[])
    full = catalog.save_inventory(config, model)
    assert catalog.inventory_collected(names_only, config) == []
    assert catalog.inventory_collected(full, config) == ["columns", "structural"]
    flags = {item["id"]: item["metadata_complete"] for item in catalog.inventories(config)}
    assert flags == {names_only: False, full: True}
    assert catalog.load_inventory(names_only, config) == model  # still usable for matching
    with pytest.raises(ValueError, match="names only"):
        catalog.load_inventory(names_only, config, require_complete=True)
    catalog.load_inventory(full, config, require_complete=True)


# -- API ---------------------------------------------------------------------------


def _models(source_schemas, target_schemas):
    return [
        DatabaseModel(database_type="oracle", schemas=source_schemas),
        DatabaseModel(database_type="azure_postgresql", schemas=target_schemas),
    ]


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_plan_with_scope_discovers_names_only_for_selected_schemas(client, monkeypatch):
    discover = AsyncMock(side_effect=_models([_schema("MIGRATION_TEST", ("A", "B"))],
                                             [_schema("migration_test", ("a", "b"))]))
    monkeypatch.setattr(routes._discovery_service, "discover", discover)
    payload = {"source": SOURCE, "target": TARGET,
               "source_schemas": ["MIGRATION_TEST"], "target_schemas": ["migration_test"]}
    response = await client.post("/api/plan", json=payload)
    assert response.status_code == 200, response.text
    plan = response.json()

    (source_call, target_call) = discover.await_args_list
    assert source_call.args[1] == ["MIGRATION_TEST"] and target_call.args[1] == ["migration_test"]
    for call in (source_call, target_call):
        assert call.kwargs == {"include_columns": False, "include_structural": False,
                               "require_all_schemas": True}
    assert plan["metadata_complete"] is False
    assert plan["source_scope"] == ["MIGRATION_TEST"] and plan["target_scope"] == ["migration_test"]
    assert plan["schema_matches"][0]["source"] == "MIGRATION_TEST"
    assert plan["schema_matches"][0]["target"] == "migration_test"
    assert len(plan["schema_matches"][0]["matched_tables"]) == 2
    catalog = Catalog()
    ids = (plan["source_inventory_id"], plan["target_inventory_id"])
    config = MigrationConfig(migration={"name": "x"}, source=SOURCE, target=TARGET)
    assert catalog.inventory_collected(ids[0], config.source) == []
    assert catalog.inventory_collected(ids[1], config.target) == []

    # A saved names-only inventory reloads with the same flag and scope.
    reloaded = await client.post("/api/inventories/plan", json={
        **payload, "source_inventory_id": ids[0], "target_inventory_id": ids[1],
        "mapping": plan["saved_mapping"],
    })
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["metadata_complete"] is False
    assert reloaded.json()["source_scope"] == ["MIGRATION_TEST"]


async def test_plan_without_scope_keeps_legacy_full_discovery(client, monkeypatch):
    discover = AsyncMock(side_effect=_models([_schema("HR")], [_schema("hr")]))
    monkeypatch.setattr(routes._discovery_service, "discover", discover)
    response = await client.post("/api/plan", json={"source": SOURCE, "target": TARGET})
    assert response.status_code == 200, response.text
    assert response.json()["metadata_complete"] is True
    for call in discover.await_args_list:
        assert call.args[1] is None
        assert call.kwargs == {"include_columns": True, "include_structural": True,
                               "require_all_schemas": False}


@pytest.mark.parametrize("scope", [{"source_schemas": []}, {"target_schemas": [" "]}])
async def test_plan_rejects_explicit_empty_scope(client, monkeypatch, scope):
    discover = AsyncMock()
    monkeypatch.setattr(routes._discovery_service, "discover", discover)
    response = await client.post("/api/plan", json={"source": SOURCE, "target": TARGET, **scope})
    assert response.status_code == 422
    discover.assert_not_awaited()


async def test_plan_reports_an_invisible_schema(client, monkeypatch):
    async def discover(config, schemas=None, **kwargs):
        raise ConfigurationError("Schema not found or not visible to this connection: NOPE")

    monkeypatch.setattr(routes._discovery_service, "discover", discover)
    response = await client.post("/api/plan", json={
        "source": SOURCE, "target": TARGET, "source_schemas": ["NOPE"], "target_schemas": ["x"]})
    assert response.status_code == 400
    assert "NOPE" in response.json()["detail"]


async def test_scoped_plan_does_not_restore_mapping_outside_the_selection(client, monkeypatch):
    # An earlier, wider plan saved a mapping for HR and SALES.
    wide = AsyncMock(side_effect=_models([_schema("HR"), _schema("SALES")],
                                         [_schema("hr"), _schema("sales")]))
    monkeypatch.setattr(routes._discovery_service, "discover", wide)
    first = (await client.post("/api/plan", json={"source": SOURCE, "target": TARGET})).json()
    mapping = {"schemas": {"HR": "hr", "SALES": "sales"}, "tables": {"SALES.T": "sales.t"},
               "columns": {}, "included_objects": ["SALES.T"], "excluded_objects": ["SALES"]}
    config = MigrationConfig(migration={"name": "x"}, source=SOURCE, target=TARGET)
    Catalog().save_mapping(config.source, config.target, first["source_inventory_id"],
                           first["target_inventory_id"], mapping)

    narrow = AsyncMock(side_effect=_models([_schema("HR"), _schema("NEW")],
                                           [_schema("hr"), _schema("new")]))
    monkeypatch.setattr(routes._discovery_service, "discover", narrow)
    response = await client.post("/api/plan", json={
        "source": SOURCE, "target": TARGET,
        "source_schemas": ["HR", "NEW"], "target_schemas": ["hr", "new"]})
    assert response.status_code == 200, response.text
    saved = response.json()["saved_mapping"]
    assert saved["schemas"] == {"HR": "hr", "NEW": "new"}
    assert saved["tables"] == {} and saved["included_objects"] == []
    assert saved["excluded_objects"] == []


async def test_schema_listing_endpoint_is_lightweight(client, monkeypatch):
    listed = AsyncMock(return_value=DatabaseModel(
        database_type="oracle", version="19c", schemas=[SchemaModel(name="HR"), SchemaModel(name="SALES")]))
    monkeypatch.setattr(routes._discovery_service, "list_schemas", listed)
    response = await client.post("/api/schemas", json=SOURCE)
    assert response.status_code == 200, response.text
    assert response.json() == {"database_type": "oracle", "version": "19c",
                               "schemas": ["HR", "SALES"]}


# -- validation honours the saved scope --------------------------------------------


async def test_full_validation_without_mapping_stays_inside_the_schema_scope(
    monkeypatch, tmp_path, oracle_conn_config, pg_conn_config,
):
    from app.adapters.factory import adapter_factory
    from app.core.config import Settings
    from app.services.migration_service import MigrationService

    source = _spy(MockAdapter(DatabaseType.ORACLE, [_schema("HR"), _schema("OTHER")]))
    target = _spy(MockAdapter(DatabaseType.AZURE_POSTGRESQL, [_schema("hr"), _schema("other")]))
    monkeypatch.setattr(adapter_factory, "create",
                        lambda config: source if config.type == DatabaseType.ORACLE else target)
    config = MigrationConfig(
        migration={"name": "Scoped"}, source=oracle_conn_config, target=pg_conn_config,
        source_schemas=["HR"], target_schemas=["hr"],
        validation={"selected_checks": ["row_count"]},
    )
    service = MigrationService(Settings(report_dir=tmp_path / "reports", run_log_dir=tmp_path / "logs"))
    run = await service.run_validation(config)
    assert run.report.overall_status == "PASS"
    assert [c.args[0] for c in source.get_tables.await_args_list] == ["HR"]
    assert [c.args[0] for c in target.get_tables.await_args_list] == ["hr"]
    source.get_schemas.assert_awaited_once_with(["HR"])
    target.get_schemas.assert_awaited_once_with(["hr"])
