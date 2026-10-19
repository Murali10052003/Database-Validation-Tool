from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api import routes
from app.core.config import MigrationConfig, Settings
from app.core.enums import DatabaseType
from app.models.database import ConnectionResult
from app.services.migration_service import MigrationService
from app.services.run_log_service import RunAlreadyExistsError, RunLogService


def test_background_worker_returns_before_validation_finishes(tmp_path, monkeypatch,
                                                             oracle_conn_config, pg_conn_config):
    import asyncio
    import threading

    from app.core.catalog import Catalog
    from app.services.background_validation import BackgroundValidation, ValidationBusyError

    service = MigrationService(Settings(run_log_dir=tmp_path / "logs", report_dir=tmp_path / "reports"))
    entered = threading.Event()
    release = threading.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 10)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(service._validation, "validate", blocked)
    config = MigrationConfig(migration={"name": "Background"},
                             source=oracle_conn_config, target=pg_conn_config)
    config.source.password = SecretStr("memory-only")
    worker = BackgroundValidation(service)
    try:
        run_id = worker.submit(config)
        assert entered.wait(5)
        assert Catalog().run_state(run_id)["status"] == "running"
        with pytest.raises(ValidationBusyError):
            worker.submit(config)
        thread = worker._thread
        release.set()
        thread.join(5)
        assert Catalog().run_state(run_id)["status"] == "failed"
        assert not config.source.password.get_secret_value()
        assert "memory-only" not in str(Catalog().runs())
    finally:
        release.set()
        worker.shutdown()


async def test_background_api_survives_client_close(tmp_path, monkeypatch):
    import asyncio
    import threading

    from app.core.catalog import Catalog
    from app.models.result import ValidationResult
    from app.reporting.report_builder import ReportBuilder
    from app.services.background_validation import BackgroundValidation

    service = MigrationService(Settings(run_log_dir=tmp_path / "logs", report_dir=tmp_path / "reports"))
    worker = BackgroundValidation(service)
    entered = threading.Event()
    release = threading.Event()
    result = ValidationResult(check_id="row_count:HR.A", category="ROW_COUNT", status="PASS")

    async def blocked(config, run_id, **kwargs):
        catalog = Catalog()
        catalog.plan_stages(run_id, ["row_count"])
        catalog.record_stage(run_id, "row_count", "running")
        catalog.record_result(run_id, "row_count", result)
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        catalog.record_stage(run_id, "row_count", "completed")
        return ReportBuilder().build(run_id, config.migration.name, config.validation.profile, [result])

    monkeypatch.setattr(service._validation, "validate", blocked)
    monkeypatch.setattr(routes, "_run_logs", service._logs)
    monkeypatch.setattr(routes, "_report_service", service._reports)
    app = FastAPI()
    app.state.validation_worker = worker
    app.include_router(routes.router)
    payload = {"source": {"type": "oracle", "host": "source", "username": "reader", "password": "secret-source"},
               "target": {"type": "azure_postgresql", "host": "target", "username": "reader", "password": "secret-target"}}
    run_id = "1" * 12
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/validations?run_id={run_id}", json=payload)
            assert response.status_code == 202, response.text
            assert response.json() == {"run_id": run_id, "status_url": f"/api/runs/{run_id}"}
            assert await asyncio.to_thread(entered.wait, 5)
            assert (await client.get(f"/api/runs/{run_id}")).json()["state"] == "running"
            partial = (await client.get(f"/api/runs/{run_id}/results")).json()
            assert partial["total"] == 1 and not partial["coverage_complete"]
            assert (await client.post("/api/validations", json=payload)).status_code == 409
            assert len(Catalog().runs()) == 1
            thread = worker._thread
        release.set()
        await asyncio.to_thread(thread.join, 5)
        assert not thread.is_alive()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as reopened:
            run = (await reopened.get(f"/api/runs/{run_id}")).json()
            assert run["state"] == "completed"
            assert run["report_id"] == run_id
            report = await reopened.get(f"/api/reports/{run_id}")
            assert report.json()["overall_status"] == "PASS"
            assert (await reopened.get(f"/api/runs/{run_id}/results")).json()["coverage_complete"]
            assert (await reopened.post(f"/api/validations?run_id={run_id}", json=payload)).status_code == 409
            assert (await reopened.post("/api/validations?run_id=invalid", json=payload)).status_code == 422
            assert (await reopened.post("/api/validations", json={})).status_code == 422
        assert not service.get(run_id).config.source.password.get_secret_value()
        assert not service.get(run_id).config.target.password.get_secret_value()
        assert "secret-source" not in str(Catalog().runs())
        assert "secret-target" not in service._logs.events(run_id).__str__()
        assert "secret-source" not in report.text
    finally:
        release.set()
        await asyncio.to_thread(worker.shutdown)


def test_background_shutdown_preserves_results(tmp_path, monkeypatch, oracle_conn_config, pg_conn_config):
    import asyncio
    import threading

    from app.core.catalog import Catalog
    from app.models.result import ValidationResult
    from app.services.background_validation import BackgroundValidation, ValidationBusyError

    service = MigrationService(Settings(run_log_dir=tmp_path / "logs", report_dir=tmp_path / "reports"))
    entered = threading.Event()
    config = MigrationConfig(migration={"name": "Stopping"}, source=oracle_conn_config, target=pg_conn_config)
    config.target.entra_token = SecretStr("shutdown-secret")

    async def blocked(config, run_id, **kwargs):
        catalog = Catalog()
        catalog.plan_stages(run_id, ["row_count", "null_count"])
        catalog.record_stage(run_id, "row_count", "running")
        catalog.record_result(run_id, "row_count", ValidationResult(
            check_id="row_count:HR.A", category="ROW_COUNT", status="PASS"))
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(service._validation, "validate", blocked)
    worker = BackgroundValidation(service)
    try:
        run_id = worker.submit(config)
        assert entered.wait(5)
    finally:
        worker.shutdown()
    partial = Catalog().partial_report(run_id)
    assert partial["state"] == "interrupted"
    assert partial["total"] == 1 and not partial["coverage_complete"]
    assert [stage["status"] for stage in partial["stages"]] == ["interrupted", "pending"]
    assert config.target.entra_token is None
    assert service._logs.get(run_id)["state"] == "interrupted"
    with pytest.raises(ValidationBusyError):
        worker.submit(config)


async def test_worker_lifespan_recovers_queue_and_excludes_second_backend(tmp_path, monkeypatch,
                                                                       oracle_conn_config, pg_conn_config):
    from filelock import Timeout

    from app.core.catalog import Catalog
    from app.main import create_app
    from app.services.background_validation import ValidationBusyError

    monkeypatch.setenv("MV_RUN_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MV_REPORT_DIR", str(tmp_path / "reports"))
    config = MigrationConfig(migration={"name": "Queued"}, source=oracle_conn_config, target=pg_conn_config)
    catalog = Catalog()
    catalog.start_run("2" * 12, config, status="queued")
    app = create_app()
    async with app.router.lifespan_context(app):
        assert catalog.run_state("2" * 12)["status"] == "interrupted"
        other = create_app()
        with pytest.raises(Timeout):
            async with other.router.lifespan_context(other):
                pytest.fail("A second backend must not recover an active backend's runs")
    with pytest.raises(ValidationBusyError):
        app.state.validation_worker.submit(config)
    async with other.router.lifespan_context(other):
        assert other.state.validation_worker is not None


async def test_background_api_requires_worker():
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/validations", json={
            "source": {"type": "oracle", "host": "source", "username": "reader"},
            "target": {"type": "azure_postgresql", "host": "target", "username": "reader"},
        })
    assert response.status_code == 503


async def test_single_connection_does_not_require_other_side(monkeypatch):
    test_one = AsyncMock(return_value=ConnectionResult(
        success=True, database_type=DatabaseType.ORACLE, message="Connected"))
    test_both = AsyncMock()
    monkeypatch.setattr(routes._migration_service, "test_connection", test_one)
    monkeypatch.setattr(routes._migration_service, "test_connections", test_both)
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/test-connection/single", json={
            "type": "oracle", "host": "host.docker.internal", "username": "reader",
        })
    assert response.status_code == 200
    assert response.json()["success"] is True
    test_one.assert_awaited_once()
    test_both.assert_not_called()


async def test_single_connection_closes_adapter(monkeypatch, oracle_conn_config):
    adapter = AsyncMock()
    adapter.test_connection.side_effect = RuntimeError("unavailable")
    monkeypatch.setattr("app.services.migration_service.adapter_factory.create", lambda config: adapter)
    with pytest.raises(RuntimeError):
        await routes._migration_service.test_connection(oracle_conn_config)
    adapter.close.assert_awaited_once()


async def test_validation_error_never_echoes_token():
    from app.main import create_app
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/test-connection/single", json={
            "type": "azure_postgresql", "entra_token": "must-not-echo", "auth_method": "entra",
        })
    assert response.status_code == 422
    assert "must-not-echo" not in response.text


async def test_browser_config_is_public_ids_only(monkeypatch):
    monkeypatch.setenv("MV_ENTRA_CLIENT_ID", "client-id")
    monkeypatch.setenv("MV_ENTRA_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "never-return")
    assert routes.auth_config() == {"client_id": "client-id", "tenant_id": "tenant-id"}


async def test_failed_run_clears_in_memory_browser_token(tmp_path, monkeypatch, oracle_conn_config, pg_conn_config):
    service = MigrationService(Settings(run_log_dir=tmp_path / "logs", report_dir=tmp_path / "reports"))
    monkeypatch.setattr(service._validation, "validate", AsyncMock(side_effect=RuntimeError("failure")))
    pg_conn_config.entra_token = SecretStr("ephemeral-secret")
    pg_conn_config.entra_token_expires_at = 9999999999
    config = MigrationConfig(
        migration={"name": "Browser token cleanup"},
        source=oracle_conn_config, target=pg_conn_config,
    )
    with pytest.raises(RuntimeError):
        await service.run_validation(config, run_id="bbbbbbbbbbbb")
    assert service.get("bbbbbbbbbbbb").config.target.entra_token is None
    assert config.target.entra_token_expires_at is None


async def test_run_api_filters_paginates_and_downloads(tmp_path, monkeypatch):
    store = RunLogService(Settings(run_log_dir=tmp_path / "logs"))
    monkeypatch.setattr(routes, "_run_logs", store)
    store.start("000000000001", "API test", "full")
    store.append("000000000001", "warning", "sample_data", "check_finished", check_id="sample_data:HR.T", status="SKIPPED")
    store.finish("000000000001", "completed", "WARNING")
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/runs")).json()[0]["outcome"] == "WARNING"
        assert (await client.get("/api/runs/unknown")).status_code == 404
        result = (await client.get("/api/runs/000000000001/events", params={"stage": "sample_data", "query": "HR.T"})).json()
        assert result["total"] == 1
        assert result["items"][0]["details"]["status"] == "SKIPPED"
        assert (await client.get("/api/runs/000000000001/events?limit=501")).status_code == 422
        assert (await client.get("/api/runs/000000000001/events?offset=2&limit=1")).json()["total"] == 3
        download = await client.get("/api/runs/000000000001/download")
        assert download.status_code == 200
        assert len(download.text.splitlines()) == 4
        assert "attachment" in download.headers["content-disposition"]


async def test_duplicate_run_returns_conflict(monkeypatch, oracle_conn_config, pg_conn_config):
    monkeypatch.setattr(routes._migration_service, "run_validation",
                        AsyncMock(side_effect=RunAlreadyExistsError("Run ID already exists")))
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/validate?run_id=000000000001", json={
            "source": oracle_conn_config.model_dump(
                mode="json", exclude={"options", "connect_timeout_seconds"}),
            "target": pg_conn_config.model_dump(
                mode="json", exclude={"options", "connect_timeout_seconds"}),
        })
    assert response.status_code == 409, response.text


async def test_partial_results_and_recovered_run_state(tmp_path, monkeypatch, oracle_conn_config, pg_conn_config):
    from app.core.catalog import Catalog
    from app.models.result import ValidationResult

    store = RunLogService(Settings(run_log_dir=tmp_path / "logs"))
    monkeypatch.setattr(routes, "_run_logs", store)
    run_id = "c" * 12
    store.start(run_id, "Interrupted", "quick")
    catalog = Catalog()
    catalog.start_run(run_id, MigrationConfig(migration={"name": "Interrupted"},
                                              source=oracle_conn_config, target=pg_conn_config))
    catalog.plan_stages(run_id, ["row_count", "null_count"])
    catalog.record_stage(run_id, "row_count", "running")
    for table in ["HR.A", "HR.B"]:
        catalog.record_result(run_id, "row_count", ValidationResult(
            check_id=f"row_count:{table}", category="ROW_COUNT", status="PASS", source_object=table))
    catalog.recover_runs()
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/runs/{run_id}/results?limit=1&offset=1")
        assert response.status_code == 200
        partial = response.json()
        assert partial["total"] == 2
        assert partial["counts"] == {"PASS": 2}
        assert partial["coverage_complete"] is False
        assert partial["state"] == "interrupted"
        assert partial["results"][0]["source_object"] == "HR.B"
        assert "overall_status" not in partial
        assert (await client.get(f"/api/runs/{run_id}")).json()["state"] == "interrupted"
        assert (await client.get("/api/runs")).json()[0]["state"] == "interrupted"
        assert (await client.get(f"/api/runs/{run_id}/results?limit=501")).status_code == 422
        assert (await client.get(f"/api/runs/{run_id}/results?offset=-1")).status_code == 422
        assert (await client.get("/api/runs/not-a-run/results")).status_code == 404
        monkeypatch.setattr(store, "get", lambda identifier: None)
        assert (await client.get(f"/api/runs/{run_id}/results")).status_code == 200