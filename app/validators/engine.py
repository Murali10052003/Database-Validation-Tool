"""The validation engine.

Runs a profile-selected set of validators in a fixed, safe order:
connectivity -> discovery -> structural/data validators. Each validator runs in
isolation so an exception in one becomes an ``ERROR`` result rather than aborting
the whole run.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.core.enums import (
    Severity,
    ValidationCategory,
    ValidationProfile,
    ValidationStatus,
)
from app.core.logging import get_logger
from app.discovery.database_discovery import DatabaseDiscovery
from app.discovery.scoped_discovery import needs_structural
from app.models.result import ValidationResult
from app.validators.aggregate import AggregateValidator
from app.validators.base import ResultPersistenceError, ValidationContext, Validator
from app.validators.checksum import ChecksumValidator
from app.validators.connectivity import ConnectivityValidator
from app.validators.constraints import ConstraintValidator
from app.validators.custom_query import CustomQueryValidator
from app.validators.indexes import IndexValidator
from app.validators.null_count import NullCountValidator
from app.validators.partitions import PartitionValidator
from app.validators.referential_integrity import ReferentialIntegrityValidator
from app.validators.routines import RoutineValidator
from app.validators.row_count import RowCountValidator
from app.validators.rules import RulesValidator
from app.validators.schema import SchemaValidator
from app.validators.sequences import SequenceValidator
from app.validators.triggers import TriggerValidator
from app.validators.views import ViewValidator

logger = get_logger(__name__)

ProgressCallback = Callable[[str, int, int], None]

# Which validators each profile runs (after connectivity + discovery). Order is
# significant: cheaper structural checks precede expensive data checks.
_STRUCTURAL = [
    "schema",
    "constraints",
    "indexes",
    "sequences",
    "views",
    "routines",
    "triggers",
    "partitions",
    "rules",
]
_PROFILE_VALIDATORS: dict[ValidationProfile, list[str]] = {
    ValidationProfile.QUICK: ["schema", "row_count"],
    ValidationProfile.STANDARD: [*_STRUCTURAL, "row_count", "null_count", "custom_query"],
    ValidationProfile.FULL: [
        *_STRUCTURAL,
        "row_count",
        "null_count",
        "aggregate",
        "referential_integrity",
        "checksum",
        "custom_query",
    ],
    ValidationProfile.CUSTOM: [*_STRUCTURAL, "row_count", "null_count", "custom_query"],
}


class ValidationEngine:
    """Orchestrates a full validation run for a source/target pair."""

    def __init__(self) -> None:
        self._registry: dict[str, type[Validator]] = {
            "schema": SchemaValidator,
            "constraints": ConstraintValidator,
            "indexes": IndexValidator,
            "sequences": SequenceValidator,
            "views": ViewValidator,
            "routines": RoutineValidator,
            "triggers": TriggerValidator,
            "partitions": PartitionValidator,
            "rules": RulesValidator,
            "row_count": RowCountValidator,
            "null_count": NullCountValidator,
            "aggregate": AggregateValidator,
            "referential_integrity": ReferentialIntegrityValidator,
            "checksum": ChecksumValidator,
            "custom_query": CustomQueryValidator,
        }

    async def run(
        self,
        ctx: ValidationContext,
        profile: ValidationProfile,
        progress: ProgressCallback | None = None,
    ) -> list[ValidationResult]:
        """Execute connectivity, discovery and the profile's validators."""
        try:
            return await self._run(ctx, profile, progress)
        finally:
            await ctx.close_profiling()

    async def _run(
        self,
        ctx: ValidationContext,
        profile: ValidationProfile,
        progress: ProgressCallback | None = None,
    ) -> list[ValidationResult]:
        from app.services.run_log_service import emit, error_code

        results: list[ValidationResult] = []
        validator_keys = self.selected_stages(profile, ctx.config.validation.selected_checks)[2:]
        ctx.selected_checks = frozenset(validator_keys)
        total_steps = 2 + len(validator_keys)  # connectivity + discovery + validators
        step = 0

        # 1. Connectivity — always first.
        step += 1
        _report(progress, "connectivity", step, total_steps)
        conn_results = await self._safe_run(ConnectivityValidator(), ctx)
        results.extend(conn_results)
        if any(r.status == ValidationStatus.ERROR for r in conn_results):
            logger.error("connectivity_failed", extra={"stage": "connectivity"})
            return results

        # 2. Discovery — required by structural and data validators.
        step += 1
        _report(progress, "discovery", step, total_steps)
        discovery_start = time.perf_counter()
        ctx.record_stage("discovery", "running")
        discovery_error = await self._discover(
            ctx,
                 include_columns=(profile != ValidationProfile.QUICK
                         or any(key not in {"schema", "row_count"} for key in validator_keys)),
                 include_structural=needs_structural(validator_keys),
        )
        if discovery_error is not None:
            ctx.record_result(discovery_error)
            ctx.record_stage("discovery", "error")
            emit(
                "error", "discovery", "stage_finished", status="ERROR",
                check_id="discovery",
                duration_ms=int((time.perf_counter() - discovery_start) * 1000),
                error_code=error_code(discovery_error.error),
            )
            results.append(discovery_error)
            return results
        ctx.record_stage("discovery", "completed")
        emit(
            "info", "discovery", "stage_finished", status="PASS",
            duration_ms=int((time.perf_counter() - discovery_start) * 1000),
        )

        # 3. Profile validators.
        for key in validator_keys:
            step += 1
            _report(progress, key, step, total_steps)
            validator_cls = self._registry.get(key)
            if validator_cls is None:
                continue
            results.extend(await self._safe_run(validator_cls(), ctx))

        return results

    async def _discover(
        self, ctx: ValidationContext, include_columns: bool, include_structural: bool = False
    ) -> ValidationResult | None:
        """Populate source/target models on the context. Returns an ERROR result on failure."""
        try:
            from app.core.catalog import Catalog

            catalog = Catalog()
            if ctx.config.discovery_mode != "full":
                from app.discovery.scoped_discovery import load_scope, refresh_scope

                source, target = load_scope(ctx)
                if ctx.config.discovery_mode == "refresh":
                    checks = self.selected_stages(
                        ctx.config.validation.profile, ctx.config.validation.selected_checks,
                    )[2:]
                    source = await refresh_scope(ctx.source_adapter, source, checks)
                    target = await refresh_scope(ctx.target_adapter, target, checks)
                ctx.source_model, ctx.target_model = source, target
                collected = ["columns", "structural"]
            else:
                mappings = ctx.config.mapping.schemas
                source_filter = (
                    [schema for schema in mappings if not ctx.mapping.is_excluded_schema(schema)]
                    or [""]
                ) if mappings else ctx.config.source_schemas
                target_filter = (
                    [ctx.mapping.resolve_schema(schema) for schema in mappings
                     if not ctx.mapping.is_excluded_schema(schema)] or [""]
                ) if mappings else ctx.config.target_schemas
                ctx.source_model = await DatabaseDiscovery(ctx.source_adapter).discover(
                    source_filter,
                    include_columns=include_columns,
                    include_structural=include_structural,
                )
                ctx.target_model = await DatabaseDiscovery(ctx.target_adapter).discover(
                    target_filter,
                    include_columns=include_columns,
                    include_structural=include_structural,
                )
                collected = (["columns"] if include_columns else []) + (
                    ["structural"] if include_structural else [])
            if ctx.config.discovery_mode != "reuse":
                ctx.config.source_inventory_id = catalog.save_inventory(
                    ctx.config.source, ctx.source_model, collected=collected,
                )
                ctx.config.target_inventory_id = catalog.save_inventory(
                    ctx.config.target, ctx.target_model, collected=collected,
                )
            ctx.config.mapping_version_id = catalog.save_mapping(
                ctx.config.source, ctx.config.target, ctx.config.source_inventory_id,
                ctx.config.target_inventory_id, ctx.config.mapping.model_dump(mode="json"),
            )
            return None
        except Exception as exc:
            logger.error("discovery_failed", extra={"error": str(exc)})
            return ValidationResult(
                check_id="discovery",
                category=ValidationCategory.SCHEMA,
                status=ValidationStatus.ERROR,
                severity=Severity.CRITICAL,
                error=str(exc),
                message="metadata discovery failed",
            )

    @staticmethod
    def selected_stages(
        profile: ValidationProfile, selected_checks: list[str] | None = None,
    ) -> list[str]:
        if selected_checks is None:
            validators = _PROFILE_VALIDATORS[profile]
        else:
            unknown = set(selected_checks) - set(_PROFILE_VALIDATORS[ValidationProfile.FULL])
            if not selected_checks or unknown:
                raise ValueError("Select at least one supported validation check")
            validators = [name for name in _PROFILE_VALIDATORS[ValidationProfile.FULL]
                          if name in selected_checks]
        return ["connectivity", "discovery", *validators]

    @staticmethod
    async def _safe_run(validator: Validator, ctx: ValidationContext) -> list[ValidationResult]:
        """Run a validator, converting any exception into a single ERROR result."""
        from app.services.run_log_service import emit, error_code

        start = time.perf_counter()
        ctx.record_stage(validator.name, "running")
        try:
            results = await validator.validate(ctx)
        except ResultPersistenceError:
            raise
        except Exception as exc:
            logger.error("validator_error", extra={"validator": validator.name, "error": str(exc)})
            results = [*ctx.stage_results.values(),
                ValidationResult(
                    check_id=f"{validator.name}:error",
                    category=validator.category,
                    status=ValidationStatus.ERROR,
                    severity=Severity.HIGH,
                    error=str(exc),
                )
            ]
        duration = int((time.perf_counter() - start) * 1000)
        for r in results:
            if r.duration_ms is None:
                r.duration_ms = duration
                r.duration_scope = "validator"
            level = "error" if r.status in {ValidationStatus.ERROR, ValidationStatus.FAIL} else (
                "info" if r.status == ValidationStatus.PASS else "warning")
            ctx.record_result(r)
            emit(level, validator.name, "check_finished", check_id=r.check_id,
                 source_object=r.source_object, target_object=r.target_object,
                 status=r.status.value, error_code=error_code(r.error) if r.error else None)
        ctx.record_stage(validator.name, "error" if any(
            result.status == ValidationStatus.ERROR for result in results
        ) else "completed")
        emit("info", validator.name, "stage_finished", duration_ms=duration)
        return results


def _report(progress: ProgressCallback | None, stage: str, step: int, total: int) -> None:
    if progress is not None:
        progress(stage, step, total)
