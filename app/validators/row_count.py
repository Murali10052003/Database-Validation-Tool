"""Row-count validator."""

from __future__ import annotations

from app.core.enums import Severity, ValidationCategory, ValidationStatus
from app.core.exceptions import QueryError, QueryTimeoutError
from app.models.result import CheckCoverage, ValidationResult
from app.validators._target_lookup import TargetLookup
from app.validators.base import ValidationContext, Validator
from app.validators.profiling import ProfileOutcome, job_outcome


def _profiled_count(side: ProfileOutcome) -> tuple[int, bool]:
    """Row count from the shared single-scan profile, raising what prevented it."""
    if side.row_count_error is not None:
        raise side.row_count_error
    if side.row_count is None:
        raise QueryError("row count was not collected")
    return side.row_count, side.row_count_estimated


class RowCountValidator(Validator):
    """Compares exact row counts of each mapped source table against its target.

    If an exact ``COUNT(*)`` exceeds ``validation.data.timeout_seconds`` and the strategy
    is ``exact_then_estimate``, the database statistics estimate is compared instead and
    the table is reported as WARNING: an estimate is never a PASS.
    """

    name = "row_count"
    category = ValidationCategory.ROW_COUNT

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        if ctx.source_model is None:
            return []
        lookup = TargetLookup(ctx.mapping, ctx.target_model)
        results = ctx.result_buffer()
        for schema in ctx.source_model.schemas:
            if ctx.mapping.is_excluded_schema(schema.name):
                continue
            for table in schema.tables:
                if ctx.mapping.is_excluded_table(schema.name, table.name):
                    continue
                results.append(await self._compare_table(ctx, schema.name, table.name, lookup))
        return results

    async def _compare_table(
        self,
        ctx: ValidationContext,
        schema: str,
        table: str,
        lookup: TargetLookup,
    ) -> ValidationResult:
        src_fqn = f"{schema}.{table}"
        check_id = f"row_count:{src_fqn}"
        target = lookup.table(schema, table)
        if target is None:
            return ValidationResult(
                check_id=check_id,
                category=ValidationCategory.ROW_COUNT,
                object_type="TABLE",
                source_object=src_fqn,
                target_object=src_fqn,
                status=ValidationStatus.SKIPPED,
                severity=Severity.INFO,
                message="target table not found; skipping row count",
            )
        target_schema, target_table, _tgt_model = target
        tgt_fqn = f"{target_schema}.{target_table}"

        data = ctx.config.validation.data
        try:
            outcome = await job_outcome(ctx, schema, table)
            if outcome is not None:
                source_count, source_estimated = _profiled_count(outcome.source)
                target_count, target_estimated = _profiled_count(outcome.target)
            else:
                source_count, source_estimated = await self._count(
                    ctx.source_adapter, schema, table, data.timeout_seconds,
                    data.row_count_strategy,
                )
                target_count, target_estimated = await self._count(
                    ctx.target_adapter, target_schema, target_table,
                    data.timeout_seconds, data.row_count_strategy,
                )
        except Exception as exc:
            return ValidationResult(
                check_id=check_id,
                category=ValidationCategory.ROW_COUNT,
                object_type="TABLE",
                source_object=src_fqn,
                target_object=tgt_fqn,
                status=ValidationStatus.ERROR,
                severity=Severity.HIGH,
                error=str(exc),
            )

        if source_estimated or target_estimated:
            return self._estimate_result(
                check_id, src_fqn, tgt_fqn, source_count, target_count,
                source_estimated, target_estimated, data.timeout_seconds,
            )

        matched = source_count == target_count
        return ValidationResult(
            check_id=check_id,
            category=ValidationCategory.ROW_COUNT,
            object_type="TABLE",
            source_object=src_fqn,
            target_object=tgt_fqn,
            status=ValidationStatus.PASS if matched else ValidationStatus.FAIL,
            severity=Severity.INFO if matched else Severity.HIGH,
            source_value=source_count,
            target_value=target_count,
            coverage=CheckCoverage(
                mode="database_count", source_rows_reported=source_count,
                target_rows_reported=target_count,
            ),
            validation_scope=(
                "Database-reported row totals; not rows fetched or physical rows scanned"
            ),
            differences=(
                [] if matched else [f"row count mismatch: {source_count} vs {target_count}"]
            ),
        )

    @staticmethod
    async def _count(
        adapter, schema: str, table: str, timeout_seconds: float, strategy: str
    ) -> tuple[int, bool]:
        """Return ``(count, is_estimate)``; estimate only after an exact-count timeout."""
        try:
            return await adapter.get_row_count_with_timeout(schema, table, timeout_seconds), False
        except QueryTimeoutError as timeout_error:
            if strategy != "exact_then_estimate":
                raise
            try:
                estimate = await adapter.get_row_count_estimate(schema, table)
            except Exception:
                estimate = None
            if estimate is None:
                raise QueryTimeoutError(
                    f"{timeout_error}; no database statistics are available to estimate it "
                    "(gather statistics, for example ANALYZE)"
                ) from timeout_error
            return estimate, True

    @staticmethod
    def _estimate_result(
        check_id: str, src_fqn: str, tgt_fqn: str, source_count: int, target_count: int,
        source_estimated: bool, target_estimated: bool, timeout_seconds: float,
    ) -> ValidationResult:
        def describe(count: int, estimated: bool) -> str:
            return f"~{count:,} estimated" if estimated else f"{count:,} exact"

        differences = [
            f"exact COUNT(*) exceeded {timeout_seconds:g}s; compared database statistics "
            f"instead (source {describe(source_count, source_estimated)}, "
            f"target {describe(target_count, target_estimated)}); approximate, not verified"
        ]
        if source_count != target_count:
            differences.append(
                f"counts differ: {source_count:,} vs {target_count:,}; "
                "re-run with a longer timeout to confirm"
            )
        return ValidationResult(
            check_id=check_id,
            category=ValidationCategory.ROW_COUNT,
            object_type="TABLE",
            source_object=src_fqn,
            target_object=tgt_fqn,
            status=ValidationStatus.WARNING,
            severity=Severity.MEDIUM,
            source_value=source_count,
            target_value=target_count,
            coverage=CheckCoverage(
                mode="statistics_estimate",
                source_rows_reported=source_count,
                target_rows_reported=target_count,
                source_estimated=source_estimated,
                target_estimated=target_estimated,
            ),
            validation_scope=(
                "Database statistics estimate after an exact-count timeout; "
                "not an exact row count and not proof that the counts match"
            ),
            message="exact row count timed out; result is an unverified statistics estimate",
            differences=differences,
        )
