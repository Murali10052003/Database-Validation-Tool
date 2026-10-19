"""Validation service.

Builds a :class:`ValidationContext` from a :class:`MigrationConfig`, runs the
:class:`ValidationEngine`, and assembles a :class:`ValidationReport`. Adapter
lifecycle is fully managed here.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.adapters.factory import adapter_factory
from app.core.config import MigrationConfig
from app.core.enums import ValidationProfile
from app.core.logging import get_logger
from app.mapping.mapping_resolver import MappingResolver
from app.models.database import DatabaseInfo, DatabaseModel
from app.reporting.report_builder import ReportBuilder, RunCoverage, ValidationReport
from app.services.run_log_service import emit, error_code
from app.validators.base import ValidationContext
from app.validators.engine import ProgressCallback, ValidationEngine

logger = get_logger(__name__)


class ValidationService:
    """Runs a full validation pass and returns a report."""

    def __init__(self) -> None:
        self._engine = ValidationEngine()
        self._builder = ReportBuilder()

    async def validate(
        self,
        config: MigrationConfig,
        migration_id: str,
        *,
        profile: ValidationProfile | None = None,
        progress: ProgressCallback | None = None,
    ) -> ValidationReport:
        profile = profile or config.validation.profile
        started_at = datetime.now(UTC)
        reached: list[str] = []

        def stage_progress(stage: str, step: int, total: int) -> None:
            reached.append(stage)
            emit("info", stage, "stage_started")
            if progress:
                progress(stage, step, total)

        source_adapter = adapter_factory.create(config.source)
        target_adapter = adapter_factory.create(config.target)
        ctx = ValidationContext(
            source_adapter=source_adapter,
            target_adapter=target_adapter,
            mapping=MappingResolver(config.mapping),
            config=config,
            source_type=config.source.type,
            target_type=config.target.type,
            target_capabilities=target_adapter.capabilities(),
        )

        from app.core.catalog import Catalog

        start = time.perf_counter()
        try:
            catalog = Catalog()
            if catalog.run_state(migration_id) is not None:
                stages = self._engine.selected_stages(profile, config.validation.selected_checks)
                catalog.plan_stages(migration_id, stages)
                ctx.result_sink = lambda stage, result: catalog.record_result(
                    migration_id, stage, result,
                )
                ctx.stage_sink = lambda stage, status: catalog.record_stage(
                    migration_id, stage, status,
                )
            results = await self._engine.run(ctx, profile, stage_progress)
        finally:
            await self._safe_close(source_adapter.close)
            await self._safe_close(target_adapter.close)
        duration_ms = int((time.perf_counter() - start) * 1000)

        report = self._builder.build(
            migration_id=migration_id,
            migration_name=config.migration.name,
            profile=profile,
            results=results,
            source=self._info_from_model(ctx.source_model, config),
            target=self._info_from_model(ctx.target_model, config, target=True),
            duration_ms=duration_ms,
        )
        selected = self._engine.selected_stages(profile, config.validation.selected_checks)
        report.run_id = migration_id
        report.started_at = started_at
        report.finished_at = datetime.now(UTC)
        report.coverage = RunCoverage(
            discovery_mode=config.discovery_mode,
            source_inventory_id=config.source_inventory_id,
            target_inventory_id=config.target_inventory_id,
            mapping_version_id=config.mapping_version_id,
            metadata_warning=("Saved metadata was reused and may be stale; data checks were live."
                              if config.discovery_mode == "reuse" else None),
            selected_stages=selected,
            not_selected_stages=[
                stage for stage in self._engine.selected_stages(ValidationProfile.FULL)
                if stage not in selected
            ],
            reached_stages=reached,
            not_reached_stages=[stage for stage in selected if stage not in reached],
            included_objects=config.mapping.included_objects,
            excluded_objects=list(dict.fromkeys([
                *config.mapping.excluded_objects,
                                *(schema for schema, target in config.mapping.schemas.items()
                                    if not target.strip()),
            ])),
            schema_options=config.validation.schema_options.model_dump(),
            checksum_limit=config.validation.data.chunk_size,
        )
        return report

    @staticmethod
    def _info_from_model(
        model: DatabaseModel | None, config: MigrationConfig, *, target: bool = False
    ) -> DatabaseInfo | None:
        if model is None:
            return None
        return DatabaseInfo(
            database_type=model.database_type,
            platform=model.platform,
            version=model.version,
        )

    @staticmethod
    async def _safe_close(close) -> None:
        try:
            await close()
            emit("info", "cleanup", "adapter_closed")
        except Exception as exc:  # pragma: no cover - defensive cleanup
            emit("warning", "cleanup", "adapter_close_failed", error_code=error_code(exc))
            logger.warning("adapter_close_failed", extra={"error": str(exc)})
