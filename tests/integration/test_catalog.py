import sqlite3

import pytest

from app.core.catalog import Catalog
from app.core.config import DatabaseConnectionConfig
from app.models.database import DatabaseModel


def test_v1_upgrade_backs_up_and_preserves_results_after_interruption(tmp_path):
    from app.core.config import MigrationConfig
    from app.models.result import ValidationResult

    path = tmp_path / "catalog.sqlite3"
    catalog = Catalog(path)
    profile = catalog.save_connection(dict(label="Keep", type="oracle", host="h", username="u"))
    with sqlite3.connect(path) as connection:
        connection.executescript("DROP TABLE run_results; DROP TABLE run_stages; "
                                 "DELETE FROM schema_migrations WHERE version=2; PRAGMA user_version=1;")
    catalog = Catalog(path)
    assert catalog.connections() == [profile]
    backups = list((tmp_path / "backups").glob("catalog-v1-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    config = MigrationConfig(migration={"name": "Journal"},
                             source={"type": "oracle", "host": "h", "username": "u"},
                             target={"type": "azure_postgresql", "host": "t", "username": "u"})
    catalog.start_run("a" * 12, config)
    catalog.plan_stages("a" * 12, ["row_count", "null_count"])
    catalog.record_stage("a" * 12, "row_count", "running")
    result = ValidationResult(check_id="row_count:HR.T", category="ROW_COUNT", status="PASS",
                              source_object="HR.T", source_value=123, target_value=123)
    catalog.record_result("a" * 12, "row_count", result)
    catalog.record_result("a" * 12, "row_count", result)
    reopened = Catalog(path)
    reopened.recover_runs()
    partial = reopened.partial_report("a" * 12)
    assert partial["state"] == "interrupted"
    assert partial["coverage_complete"] is False
    assert partial["total"] == 1
    assert partial["results"][0]["source_value"] == 123
    assert [stage["status"] for stage in partial["stages"]] == ["interrupted", "pending"]


def test_catalog_reopen_backup_and_no_passwords(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    catalog = Catalog(path)
    values = dict(label="Source", type="oracle", host="localhost", username="reader",
                  password="never-persist-this", port=1521)
    saved = catalog.save_connection(values)
    assert "password" not in saved
    assert Catalog(path).connections() == [saved]
    assert b"never-persist-this" not in path.read_bytes()
    backup = catalog.backup()
    assert Catalog(backup).connections() == [saved]
    catalog.delete_connection(saved["id"])
    assert catalog.connections() == []


def test_inventory_roundtrip_and_identity_guard(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    config = DatabaseConnectionConfig(type="oracle", host="host", username="user")
    model = DatabaseModel(database_type="oracle", schemas=[{
        "name": "HR", "tables": [{"schema_name": "HR", "name": "T", "columns": []}],
    }])
    identifier = catalog.save_inventory(config, model)
    assert catalog.load_inventory(identifier, config) == model
    config.host = "other"
    with pytest.raises(ValueError, match="connection changed"):
        catalog.load_inventory(identifier, config)


def test_unknown_version_never_resets_data(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    catalog = Catalog(path)
    catalog.save_connection(dict(label="Keep", type="oracle", host="host", username="user"))
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="Unsupported"):
        Catalog(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM connections").fetchone()[0] == 1


async def test_scoped_refresh_does_not_enumerate_schemas_or_tables(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from app.discovery.scoped_discovery import refresh_scope

    model = DatabaseModel(database_type="oracle", schemas=[{
        "name": "HR", "tables": [{"schema_name": "HR", "name": "T"}],
    }])
    adapter = AsyncMock()
    adapter.get_constraints.return_value = []
    adapter.get_indexes.return_value = []
    adapter.get_triggers.return_value = []
    adapter.get_partitions.return_value = []
    from app.models.column import ColumnModel
    adapter.get_columns.return_value = [ColumnModel(name="ID", ordinal_position=1, native_type="NUMBER")]
    refreshed = await refresh_scope(adapter, model, ["row_count"])
    adapter.get_schemas.assert_not_called()
    adapter.get_tables.assert_not_called()
    adapter.get_columns.assert_awaited_once_with("HR", "T")
    assert refreshed.schemas[0].tables[0].columns[0].name == "ID"
    assert model.schemas[0].tables[0].columns == []


def test_scoped_inventory_query_does_not_load_unselected_tables(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    config = DatabaseConnectionConfig(type="oracle", host="host", username="user")
    model = DatabaseModel(database_type="oracle", schemas=[{
        "name": "HR", "tables": [{"schema_name": "HR", "name": name} for name in ["T", "OTHER"]],
    }])
    identifier = catalog.save_inventory(config, model)
    loaded = catalog.load_inventory(identifier, config, included=["hr.t"])
    assert [table.name for table in loaded.schemas[0].tables] == ["T"]
    assert not catalog.load_inventory(identifier, config, included=["HR"], excluded=["HR"]).schemas


async def test_catalog_api_discovery_mapping_and_credentials(monkeypatch):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api import routes

    source = {"type": "oracle", "host": "source", "username": "reader"}
    target = {"type": "azure_postgresql", "host": "target", "username": "reader"}
    models = [DatabaseModel(database_type=config["type"], schemas=[{
        "name": schema, "tables": [{"schema_name": schema, "name": "T"}],
    }]) for config, schema in [(source, "HR"), (target, "public")]]
    monkeypatch.setattr(routes._discovery_service, "discover", AsyncMock(side_effect=models))
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        profile = {**source, "label": "Source"}
        assert (await client.post("/api/connections", json={**profile, "password": "secret"})).status_code == 422
        saved = (await client.post("/api/connections", json=profile)).json()
        assert (await client.get("/api/connections")).json() == [saved]
        payload = {"source": source, "target": target}
        response = await client.post("/api/plan", json=payload)
        assert response.status_code == 200, response.text
        plan = response.json()
        payload.update(source_inventory_id=plan["source_inventory_id"], target_inventory_id=plan["target_inventory_id"])
        payload["mapping"] = {"schemas": {"HR": "public"}, "tables": {"HR.T": "public.T"}, "type_overrides": {"HR.T.ID": "BIGINT"}}
        assert (await client.post("/api/mappings", json=payload)).status_code == 200
        loaded = await client.post("/api/inventories/plan", json=payload)
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["schema_matches"][0]["target"] == "public"
        found = (await client.post("/api/inventories/search", json=payload)).json()
        assert found["mappings"][0]["payload"]["type_overrides"] == {"HR.T.ID": "BIGINT"}
        assert len(found["source"]) == 1
        from app.schemas.api import MigrationRequest

        config = MigrationRequest.model_validate(payload).to_migration_config()
        config.mapping.validation_overrides = {"HR.T": "skip"}
        Catalog().save_mapping(config.source, config.target,
                       plan["source_inventory_id"], plan["target_inventory_id"],
                       config.mapping.model_dump(mode="json"))
        monkeypatch.setattr(routes._discovery_service, "discover", AsyncMock(side_effect=models))
        rediscovered = await client.post("/api/plan", json=payload)
        assert rediscovered.status_code == 200, rediscovered.text
        restored = rediscovered.json()["saved_mapping"]
        assert restored["schemas"] == {"HR": "public"}
        assert restored["validation_overrides"] == {"HR.T": "skip"}
        payload["mapping"] = restored
        assert (await client.post("/api/inventories/plan", json=payload)).status_code == 200
        restored_config = MigrationRequest.model_validate(payload).to_migration_config()
        assert restored_config.mapping.validation_overrides == {"HR.T": "skip"}
        payload["source"]["host"] = "wrong"
        assert (await client.post("/api/inventories/plan", json=payload)).status_code == 409


@pytest.mark.parametrize("mode", ["full", "refresh", "reuse"])
async def test_blank_schema_is_not_queried_in_validation(mode, monkeypatch, tmp_path,
                                                        oracle_conn_config, pg_conn_config):
    from unittest.mock import AsyncMock

    from app.adapters.factory import adapter_factory
    from app.core.config import MigrationConfig, Settings
    from app.core.enums import DatabaseType
    from app.models.column import ColumnModel
    from app.models.schema import SchemaModel
    from app.models.table import TableModel
    from app.services.migration_service import MigrationService
    from tests.conftest import MockAdapter

    def schema(name):
        return SchemaModel(name=name, tables=[TableModel(schema_name=name, name="T", columns=[
            ColumnModel(name="ID", ordinal_position=1, native_type="INTEGER"),
        ])])

    source_model = DatabaseModel(database_type="oracle", schemas=[schema("HR"), schema("SKIP")])
    target_model = DatabaseModel(database_type="azure_postgresql", schemas=[schema("hr"), schema("SKIP")])
    source = MockAdapter(DatabaseType.ORACLE, source_model.schemas)
    target = MockAdapter(DatabaseType.AZURE_POSTGRESQL, target_model.schemas)
    for adapter in (source, target):
        adapter.get_columns = AsyncMock(wraps=adapter.get_columns)
        adapter.get_row_count = AsyncMock(wraps=adapter.get_row_count)
    monkeypatch.setattr(adapter_factory, "create", lambda config: source if config.type == DatabaseType.ORACLE else target)
    catalog = Catalog()
    config = MigrationConfig(
        migration={"name": "Blank schema scope"}, source=oracle_conn_config, target=pg_conn_config,
        discovery_mode=mode, mapping={"schemas": {"HR": "hr", "SKIP": " "}},
        validation={"selected_checks": ["row_count"]},
        source_inventory_id=catalog.save_inventory(oracle_conn_config, source_model),
        target_inventory_id=catalog.save_inventory(pg_conn_config, target_model),
    )
    service = MigrationService(Settings(report_dir=tmp_path / "reports", run_log_dir=tmp_path / "logs"))
    run = await service.run_validation(config)
    assert run.report.overall_status == "PASS"
    assert "SKIP" in run.report.coverage.excluded_objects
    source.get_row_count.assert_awaited_once_with("HR", "T")
    target.get_row_count.assert_awaited_once_with("hr", "T")
    for adapter in (source, target):
        assert all(call.args[0].casefold() == "hr" for call in adapter.get_columns.await_args_list)


async def test_refresh_run_persists_exact_snapshots_and_reuses_without_discovery(
    monkeypatch, oracle_conn_config, pg_conn_config, tmp_path,
):
    from unittest.mock import AsyncMock

    from app.adapters.factory import adapter_factory
    from app.core.config import MigrationConfig, Settings
    from app.core.enums import DatabaseType
    from app.models.column import ColumnModel
    from app.models.schema import SchemaModel
    from app.models.table import TableModel
    from app.services.migration_service import MigrationService
    from tests.conftest import MockAdapter

    source_schema = SchemaModel(name="HR", tables=[TableModel(
        schema_name="HR", name="T", columns=[ColumnModel(name="ID", ordinal_position=1, native_type="NUMBER")],
    )])
    target_schema = SchemaModel(name="public", tables=[TableModel(
        schema_name="public", name="T", columns=[ColumnModel(name="ID", ordinal_position=1, native_type="INTEGER")],
    )])
    source = MockAdapter(DatabaseType.ORACLE, [source_schema])
    target = MockAdapter(DatabaseType.AZURE_POSTGRESQL, [target_schema])
    source.get_tables = AsyncMock(side_effect=AssertionError("table enumeration forbidden"))
    target.get_schemas = AsyncMock(side_effect=AssertionError("schema enumeration forbidden"))
    monkeypatch.setattr(adapter_factory, "create", lambda config: source if config.type == DatabaseType.ORACLE else target)
    catalog = Catalog()
    source_id = catalog.save_inventory(oracle_conn_config, DatabaseModel(database_type="oracle", schemas=[source_schema]))
    target_id = catalog.save_inventory(pg_conn_config, DatabaseModel(database_type="azure_postgresql", schemas=[SchemaModel(name="public")]))
    config = MigrationConfig.model_validate({
        "migration": {"name": "Scoped"}, "source": oracle_conn_config, "target": pg_conn_config,
        "discovery_mode": "refresh", "source_inventory_id": source_id, "target_inventory_id": target_id,
        "mapping": {"schemas": {"HR": "public"}, "included_objects": ["HR.T"]},
        "validation": {"selected_checks": ["row_count"]},
    })
    service = MigrationService(Settings(report_dir=tmp_path / "reports", run_log_dir=tmp_path / "logs"))
    run = await service.run_validation(config)
    assert run.report.overall_status == "PASS"
    assert run.report.coverage.source_inventory_id != source_id
    assert run.report.coverage.target_inventory_id != target_id
    stored = catalog.runs()[0]
    assert stored["configuration"]["mapping_version_id"] == run.report.coverage.mapping_version_id
    assert "password" not in stored["configuration"]["source"]
    source.get_columns = AsyncMock(side_effect=AssertionError("metadata read forbidden"))
    target.get_columns = AsyncMock(side_effect=AssertionError("metadata read forbidden"))
    config.discovery_mode = "reuse"
    reused = await service.run_validation(config)
    assert reused.report.overall_status == "PASS"
    assert reused.report.coverage.metadata_warning
    config.mapping.included_objects = ["HR.UNKNOWN"]
    rejected = await service.run_validation(config)
    assert rejected.report.overall_status == "FAIL"
    assert rejected.report.results[-1].check_id == "discovery"