"""NULL-count validation.

Compares, per mapped column, the number of NULLs in the source against the target.
A mismatch usually means the migration dropped or introduced NULLs.
"""

from __future__ import annotations

from app.core.enums import Severity, ValidationCategory, ValidationStatus
from app.models.result import CheckCoverage, ValidationResult
from app.models.table import TableModel
from app.validators._columns import null_count_columns
from app.validators._target_lookup import TargetLookup
from app.validators.base import ValidationContext, Validator
from app.validators.profiling import job_outcome


class NullCountValidator(Validator):
    """Compares NULL counts of mapped columns between source and target."""

    name = "null_count"
    category = ValidationCategory.NULL_COUNT

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
                results.extend(await self._compare_table(ctx, schema.name, table, lookup))
        return results

    async def _compare_table(
        self,
        ctx: ValidationContext,
        schema: str,
        table: TableModel,
        lookup: TargetLookup,
    ) -> list[ValidationResult]:
        src_fqn = f"{schema}.{table.name}"
        target = lookup.table(schema, table.name)
        if target is None:
            return []
        target_schema, target_table, tgt_model = target
        tgt_fqn = f"{target_schema}.{target_table}"

        columns = null_count_columns(ctx, schema, table, lookup, tgt_model)
        if not columns:
            return []
        scanned = [(src, tgt) for src, tgt, zero in columns if not zero]
        src_estimated: set[str] = set()
        tgt_estimated: set[str] = set()
        src_nulls: dict[str, int] = {}
        tgt_nulls: dict[str, int] = {}
        try:
            if scanned:
                outcome = await job_outcome(ctx, schema, table.name)
                if outcome is not None:
                    skipped = outcome.source.skipped_reason or outcome.target.skipped_reason
                    if skipped:
                        return [self._skipped(src_fqn, tgt_fqn, skipped)]
                    for side in (outcome.source, outcome.target):
                        if side.null_error is not None:
                            raise side.null_error
                    src_nulls, tgt_nulls = outcome.source.null_counts, outcome.target.null_counts
                    src_estimated = outcome.source.null_estimated
                    tgt_estimated = outcome.target.null_estimated
                else:
                    timeout = ctx.config.validation.data.timeout_seconds
                    src_names = [src for src, _ in scanned]
                    tgt_names = [tgt for _, tgt in scanned]
                    src_nulls = await ctx.source_adapter.run_bounded(
                        timeout,
                        lambda: ctx.source_adapter.get_null_counts(schema, table.name, src_names),
                        f"NULL counts of {src_fqn}",
                    )
                    tgt_nulls = await ctx.target_adapter.run_bounded(
                        timeout,
                        lambda: ctx.target_adapter.get_null_counts(
                            target_schema, target_table, tgt_names
                        ),
                        f"NULL counts of {tgt_fqn}",
                    )
        except Exception as exc:
            return [
                ValidationResult(
                    check_id=f"null_count:{src_fqn}",
                    category=ValidationCategory.NULL_COUNT,
                    object_type="TABLE",
                    source_object=src_fqn,
                    target_object=tgt_fqn,
                    status=ValidationStatus.ERROR,
                    severity=Severity.HIGH,
                    error=str(exc),
                )
            ]

        results = ctx.result_buffer()
        for src_col, tgt_col, zero in columns:
            src_n = 0 if zero else src_nulls.get(src_col, 0)
            tgt_n = 0 if zero else tgt_nulls.get(tgt_col, 0)
            estimated = not zero and (src_col in src_estimated or tgt_col in tgt_estimated)
            matched = src_n == tgt_n
            check_id = f"null_count:{src_fqn}.{src_col}"
            src_obj, tgt_obj = f"{src_fqn}.{src_col}", f"{tgt_fqn}.{tgt_col}"
            if estimated:
                results.append(self._estimate_result(
                    check_id, src_obj, tgt_obj, src_n, tgt_n,
                    src_col in src_estimated, tgt_col in tgt_estimated,
                    ctx.config.validation.data.timeout_seconds,
                ))
                continue
            results.append(
                ValidationResult(
                    check_id=check_id,
                    category=ValidationCategory.NULL_COUNT,
                    object_type="COLUMN",
                    source_object=src_obj,
                    target_object=tgt_obj,
                    status=ValidationStatus.PASS if matched else ValidationStatus.FAIL,
                    severity=Severity.INFO if matched else Severity.MEDIUM,
                    source_value=src_n,
                    target_value=tgt_n,
                    validation_scope=(
                        "NOT NULL on both sides, so no NULLs are possible; table not scanned"
                        if zero else None
                    ),
                    differences=(
                        [] if matched else [f"null count mismatch: {src_n} vs {tgt_n}"]
                    ),
                )
            )
        return results

    @staticmethod
    def _skipped(src_fqn: str, tgt_fqn: str, reason: str) -> ValidationResult:
        return ValidationResult(
            check_id=f"null_count:{src_fqn}",
            category=ValidationCategory.NULL_COUNT,
            object_type="TABLE",
            source_object=src_fqn,
            target_object=tgt_fqn,
            status=ValidationStatus.SKIPPED,
            severity=Severity.INFO,
            message=f"NULL counts not run: {reason}",
        )

    @staticmethod
    def _estimate_result(
        check_id: str, src_obj: str, tgt_obj: str, src_n: int, tgt_n: int,
        source_estimated: bool, target_estimated: bool, timeout_seconds: float,
    ) -> ValidationResult:
        def describe(count: int, estimated: bool) -> str:
            return f"~{count:,} estimated" if estimated else f"{count:,} exact"

        differences = [
            f"exact NULL count exceeded {timeout_seconds:g}s; compared database statistics "
            f"instead (source {describe(src_n, source_estimated)}, "
            f"target {describe(tgt_n, target_estimated)}); approximate, not verified"
        ]
        if src_n != tgt_n:
            differences.append(
                f"counts differ: {src_n:,} vs {tgt_n:,}; re-run with a longer timeout to confirm"
            )
        return ValidationResult(
            check_id=check_id,
            category=ValidationCategory.NULL_COUNT,
            object_type="COLUMN",
            source_object=src_obj,
            target_object=tgt_obj,
            status=ValidationStatus.WARNING,
            severity=Severity.MEDIUM,
            source_value=src_n,
            target_value=tgt_n,
            coverage=CheckCoverage(
                mode="statistics_estimate",
                source_estimated=source_estimated,
                target_estimated=target_estimated,
            ),
            validation_scope=(
                "Database statistics estimate after an exact-count timeout; "
                "not an exact NULL count and not proof that the counts match"
            ),
            message="exact NULL count timed out; result is an unverified statistics estimate",
            differences=differences,
        )
