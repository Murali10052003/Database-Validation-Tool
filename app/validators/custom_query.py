"""Custom user-defined query validation.

Runs each configured ``CustomValidationConfig``: a source query and a target query
whose scalar results are compared with a chosen operator (and optional tolerance).
Lets users assert business invariants the built-in validators cannot express.
"""

from __future__ import annotations

from app.comparison.data_comparator import values_equal
from app.core.config import CustomValidationConfig
from app.core.enums import ComparisonOperator, Severity, ValidationCategory, ValidationStatus
from app.models.result import ValidationResult
from app.validators.base import ValidationContext, Validator

_SEVERITY_BY_NAME = {s.value: s for s in Severity}


class CustomQueryValidator(Validator):
    """Executes user-defined source/target query comparisons."""

    name = "custom_query"
    category = ValidationCategory.CUSTOM_QUERY

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        checks = ctx.config.validation.custom_validations
        results = ctx.result_buffer()
        for check in checks:
            results.append(await self._run_check(ctx, check))
        return results

    async def _run_check(
        self, ctx: ValidationContext, check: CustomValidationConfig
    ) -> ValidationResult:
        check_id = f"custom_query:{check.name}"
        severity = _SEVERITY_BY_NAME.get((check.severity or "").upper(), Severity.HIGH)
        try:
            src = (await ctx.source_adapter.execute_query(check.source_query)).scalar()
            tgt = (await ctx.target_adapter.execute_query(check.target_query)).scalar()
        except Exception as exc:
            return ValidationResult(
                check_id=check_id,
                category=ValidationCategory.CUSTOM_QUERY,
                status=ValidationStatus.ERROR,
                severity=severity,
                error=str(exc),
                message=check.name,
            )

        ok = _compare(src, tgt, check.comparison, check.tolerance)
        return ValidationResult(
            check_id=check_id,
            category=ValidationCategory.CUSTOM_QUERY,
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            severity=Severity.INFO if ok else severity,
            source_value=src,
            target_value=tgt,
            message=check.name,
            differences=(
                [] if ok else [f"{check.comparison.value} check failed: {src!r} vs {tgt!r}"]
            ),
        )


def _compare(
    src: object, tgt: object, op: ComparisonOperator, tolerance: float
) -> bool:
    if op is ComparisonOperator.EQUAL:
        return values_equal(src, tgt)
    if op is ComparisonOperator.NOT_EQUAL:
        return not values_equal(src, tgt)
    src_n, tgt_n = _as_float(src), _as_float(tgt)
    if op is ComparisonOperator.GREATER_THAN:
        return src_n is not None and tgt_n is not None and src_n > tgt_n
    if op is ComparisonOperator.LESS_THAN:
        return src_n is not None and tgt_n is not None and src_n < tgt_n
    if op is ComparisonOperator.APPROXIMATE:
        if src_n is None or tgt_n is None:
            return values_equal(src, tgt)
        return abs(src_n - tgt_n) <= tolerance
    # CUSTOM (and any unhandled operator) falls back to strict equality.
    return values_equal(src, tgt)


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
