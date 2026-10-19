"""Aggregate validation (MIN/MAX/SUM/COUNT) for numeric columns.

Numeric aggregates are deterministic for correctly migrated data, so a mismatch is
strong evidence of data loss or corruption. AVG is intentionally excluded to avoid
cross-engine floating-point rounding noise.
"""

from __future__ import annotations

from app.comparison.data_comparator import numeric_equal
from app.core.enums import Severity, ValidationCategory, ValidationStatus
from app.core.exceptions import QueryError
from app.models.column import ColumnModel
from app.models.result import ValidationResult
from app.models.table import TableModel
from app.validators._columns import aggregate_columns
from app.validators._target_lookup import TargetLookup
from app.validators.base import ValidationContext, Validator
from app.validators.profiling import JobOutcome, ProfileOutcome, job_outcome

_AGGREGATES = ("min", "max", "sum", "count")


def _profiled_aggregate(side: ProfileOutcome, column: str) -> dict:
    """Aggregates of one column from the shared profile, raising what prevented them."""
    if column in side.aggregate_errors:
        raise side.aggregate_errors[column]
    if column not in side.aggregates:
        raise QueryError(f"aggregates of {column} were not collected")
    return side.aggregates[column]


class AggregateValidator(Validator):
    """Compares numeric-column aggregates between source and target."""

    name = "aggregate"
    category = ValidationCategory.AGGREGATE

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
        target = lookup.table(schema, table.name)
        if target is None:
            return []
        target_schema, target_table, tgt_model = target

        columns = aggregate_columns(ctx, schema, table, lookup, tgt_model)
        if not columns:
            return []
        outcome = await job_outcome(ctx, schema, table.name)
        if outcome is not None:
            skipped = outcome.source.skipped_reason or outcome.target.skipped_reason
            if skipped:
                fqn = f"{schema}.{table.name}"
                return [ValidationResult(
                    check_id=f"aggregate:{fqn}",
                    category=ValidationCategory.AGGREGATE,
                    object_type="TABLE",
                    source_object=fqn,
                    target_object=f"{target_schema}.{target_table}",
                    status=ValidationStatus.SKIPPED,
                    severity=Severity.INFO,
                    message=f"aggregates not run: {skipped}",
                )]
        results = ctx.result_buffer()
        for col, tgt_col in columns:
            results.append(
                await self._compare_column(
                    ctx, schema, table.name, col, target_schema, target_table, tgt_col, outcome
                )
            )
        return results

    async def _compare_column(
        self,
        ctx: ValidationContext,
        schema: str,
        table: str,
        col: ColumnModel,
        target_schema: str,
        target_table: str,
        tgt_col: str,
        outcome: JobOutcome | None = None,
    ) -> ValidationResult:
        src_fqn = f"{schema}.{table}.{col.name}"
        tgt_fqn = f"{target_schema}.{target_table}.{tgt_col}"
        check_id = f"aggregate:{src_fqn}"
        try:
            if outcome is not None:
                src_agg = _profiled_aggregate(outcome.source, col.name)
                tgt_agg = _profiled_aggregate(outcome.target, tgt_col)
            else:
                timeout = ctx.config.validation.data.timeout_seconds
                src_agg = await ctx.source_adapter.run_bounded(
                    timeout,
                    lambda: ctx.source_adapter.get_numeric_aggregates(schema, table, col.name),
                    f"Aggregates of {src_fqn}",
                )
                tgt_agg = await ctx.target_adapter.run_bounded(
                    timeout,
                    lambda: ctx.target_adapter.get_numeric_aggregates(
                        target_schema, target_table, tgt_col
                    ),
                    f"Aggregates of {tgt_fqn}",
                )
        except Exception as exc:
            return ValidationResult(
                check_id=check_id,
                category=ValidationCategory.AGGREGATE,
                object_type="COLUMN",
                source_object=src_fqn,
                target_object=tgt_fqn,
                status=ValidationStatus.ERROR,
                severity=Severity.HIGH,
                error=str(exc),
            )

        differences = [
            f"{agg} mismatch: {src_agg.get(agg)} vs {tgt_agg.get(agg)}"
            for agg in _AGGREGATES
            if not numeric_equal(src_agg.get(agg), tgt_agg.get(agg))
        ]
        matched = not differences
        return ValidationResult(
            check_id=check_id,
            category=ValidationCategory.AGGREGATE,
            object_type="COLUMN",
            source_object=src_fqn,
            target_object=tgt_fqn,
            status=ValidationStatus.PASS if matched else ValidationStatus.FAIL,
            severity=Severity.INFO if matched else Severity.HIGH,
            source_value=str(src_agg.get("sum")),
            target_value=str(tgt_agg.get("sum")),
            differences=differences,
        )
