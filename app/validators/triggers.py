"""Trigger validation."""

from __future__ import annotations

from app.comparison.object_comparator import ObjectComparator
from app.core.enums import ValidationCategory
from app.models.result import ValidationResult
from app.validators.base import ValidationContext, Validator


class TriggerValidator(Validator):
    """Compares triggers between matched source and target tables."""

    name = "triggers"
    category = ValidationCategory.TRIGGER

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        if ctx.source_model is None or ctx.target_model is None:
            return []
        comparator = ObjectComparator(
            mapping=ctx.mapping,
            source_type=ctx.source_type,
            target_type=ctx.target_type,
            target_capabilities=ctx.target_capabilities,
            result_factory=ctx.result_buffer,
        )
        return comparator.compare_triggers(ctx.source_model, ctx.target_model)
