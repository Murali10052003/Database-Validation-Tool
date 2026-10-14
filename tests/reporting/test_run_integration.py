from unittest.mock import AsyncMock

import pytest

from app.core.config import MigrationConfig, Settings
from app.core.enums import DatabaseType
from app.services.migration_service import MigrationService
from app.services.run_log_service import RunLogService
from tests.conftest import MockAdapter


async def test_run_failure_retains_logs(tmp_path, oracle_conn_config, pg_conn_config):
    config = MigrationConfig(migration={"name": "failure"}, source=oracle_conn_config, target=pg_conn_config)
    settings = Settings(report_dir=tmp_path, run_log_dir=tmp_path / "logs")
    service = MigrationService(settings)
    service._validation.validate = AsyncMock(side_effect=RuntimeError("password=secret"))
    with pytest.raises(RuntimeError):
        await service.run_validation(config)
    store = RunLogService(settings)
    run = store.runs()[0]
    assert run["state"] == "failed"
    assert run["report_id"] is None
    assert "secret" not in str(store.events(run["id"]))


async def test_quick_run_manifest_and_events(tmp_path, monkeypatch, oracle_conn_config, pg_conn_config):
    from app.adapters.factory import adapter_factory

    config = MigrationConfig(migration={"name": "quick"}, source=oracle_conn_config, target=pg_conn_config,
                             validation={"profile": "quick"})
    settings = Settings(report_dir=tmp_path, run_log_dir=tmp_path / "logs")
    monkeypatch.setattr(adapter_factory, "create", lambda connection: MockAdapter(DatabaseType.ORACLE, []))
    run = await MigrationService(settings).run_validation(config)
    assert run.report.coverage.not_reached_stages == []
    assert "checksum" in run.report.coverage.not_selected_stages
    assert run.report.run_id == run.id
    events = RunLogService(settings).events(run.id)["items"]
    assert any(event["stage"] == "cleanup" for event in events)
    assert any(event["event"] == "stage_finished" for event in events)
    assert RunLogService(settings).get(run.id)["state"] == "completed"


async def test_connection_failure_marks_unreached_stages(tmp_path, monkeypatch, oracle_conn_config, pg_conn_config):
    from app.adapters.factory import adapter_factory

    config = MigrationConfig(migration={"name": "unreachable"}, source=oracle_conn_config, target=pg_conn_config,
                             validation={"profile": "full"})
    settings = Settings(report_dir=tmp_path, run_log_dir=tmp_path / "logs")
    monkeypatch.setattr(adapter_factory, "create", lambda connection: MockAdapter(DatabaseType.ORACLE, [], connect_ok=False))
    run = await MigrationService(settings).run_validation(config)
    assert run.report.overall_status.value == "FAIL"
    assert "checksum" in run.report.coverage.not_reached_stages
    assert run.report.coverage.reached_stages == ["connectivity"]