"""Migration orchestration service.

Ties discovery, validation and reporting together and keeps an in-memory registry
of runs keyed by migration id. The registry backs the CLI's ``report`` lookup and
the (Phase 5) API; persisted JSON reports remain the source of truth across
processes.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.factory import adapter_factory
from app.core.catalog import Catalog
from app.core.config import DatabaseConnectionConfig, MigrationConfig, Settings, get_settings
from app.core.enums import ValidationProfile
from app.models.database import ConnectionResult
from app.reporting.report_builder import ValidationReport
from app.services.report_service import ReportService
from app.services.run_log_service import RunLogService, error_code
from app.services.validation_service import ValidationService
from app.validators.engine import ProgressCallback


@dataclass
class MigrationRun:
    """A single validation run and its outcome."""

    id: str
    name: str
    config: MigrationConfig
    status: str = "created"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    report: ValidationReport | None = None
    report_path: Path | None = None


class MigrationService:
    """Creates and tracks migration validation runs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._validation = ValidationService()
        self._reports = ReportService(self._settings)
        self._logs = RunLogService(self._settings)
        self._runs: dict[str, MigrationRun] = {}

    # -- registry ----------------------------------------------------------

    def create(self, config: MigrationConfig, run_id: str | None = None) -> MigrationRun:
        run = MigrationRun(
            id=run_id or uuid.uuid4().hex[:12],
            name=config.migration.name,
            config=config,
        )
        self._runs[run.id] = run
        return run

    def get(self, migration_id: str) -> MigrationRun | None:
        return self._runs.get(migration_id)

    def list(self) -> list[MigrationRun]:
        return list(self._runs.values())

    # -- operations --------------------------------------------------------

    def prepare_background_run(self, config: MigrationConfig, run_id: str) -> MigrationRun:
        catalog = Catalog()
        if catalog.run_state(run_id) is not None:
            from app.services.run_log_service import RunAlreadyExistsError

            raise RunAlreadyExistsError("Run ID already exists")
        self._logs.start(run_id, config.migration.name, config.validation.profile.value, "queued")
        try:
            catalog.start_run(run_id, config, status="queued")
        except BaseException:
            self._logs.finish(run_id, "failed")
            raise
        run = self.create(config, run_id)
        run.status = "queued"
        return run

    async def test_connection(self, config: DatabaseConnectionConfig) -> ConnectionResult:
        adapter = adapter_factory.create(config)
        try:
            return await adapter.test_connection()
        finally:
            await adapter.close()

    async def test_connections(
        self, config: MigrationConfig
    ) -> tuple[ConnectionResult, ConnectionResult]:
        """Test source then target connectivity, closing both adapters."""
        source = adapter_factory.create(config.source)
        target = adapter_factory.create(config.target)
        try:
            source_result = await source.test_connection()
            target_result = await target.test_connection()
        finally:
            await source.close()
            await target.close()
        return source_result, target_result

    async def run_validation(
        self,
        config: MigrationConfig,
        *,
        profile: ValidationProfile | None = None,
        progress: ProgressCallback | None = None,
        run_id: str | None = None,
        prepared_run: MigrationRun | None = None,
    ) -> MigrationRun:
        """Run validation for ``config`` and persist a JSON report."""
        run = prepared_run or self.create(config, run_id)
        started = prepared_run is not None
        try:
            if prepared_run is None:
                self._logs.start(run.id, run.name, (profile or config.validation.profile).value)
            started = True
            run.status = "running"
            catalog = Catalog()
            if prepared_run is None:
                catalog.start_run(run.id, config)
            else:
                catalog.activate_run(run.id)
                self._logs.append(run.id, "info", "run", "started")
            if config.source_inventory_id and config.target_inventory_id:
                config.mapping_version_id = catalog.save_mapping(
                    config.source, config.target, config.source_inventory_id,
                    config.target_inventory_id, config.mapping.model_dump(mode="json"),
                )
            with self._logs.bind(run.id):
                report = await self._validation.validate(
                    config, run.id, profile=profile, progress=progress
                )
                run.report = report
                catalog.update_run_config(run.id, config)
                run.report_path = self._reports.save_json(report)
                catalog.finish_run(run.id, report)
            run.status = report.overall_status.value
            self._logs.finish(run.id, "completed", run.status)
        except BaseException as exc:
            if not started:
                raise
            run.status = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
            if "catalog" in locals():
                if run.status == "interrupted":
                    catalog.interrupt_run(run.id)
                else:
                    catalog.finish_run(run.id, error=error_code(exc))
            self._logs.append(
                run.id, "error", "run", "execution_failed", error_code=error_code(exc),
            )
            self._logs.finish(run.id, run.status)
            raise
        finally:
            for connection in (config.source, config.target):
                connection.entra_token = None
                connection.entra_token_expires_at = None
        return run
