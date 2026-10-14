"""Schema-structure validator.

Delegates to :class:`~app.comparison.schema_comparator.SchemaComparator`, which
produces schema-, table- and column-level results in one pass. The dedicated
``tables`` and ``columns`` modules exist for structure; their comparison logic
lives in the comparator so discovery and matching happen only once.
"""

from __future__ import annotations

from app.comparison.schema_comparator import SchemaComparator
from app.core.enums import ValidationCategory
from app.models.result import ValidationResult
from app.validators.base import ValidationContext, Validator


class SchemaValidator(Validator):
    """Compares schemas, tables and columns between source and target."""

    name = "schema"
    category = ValidationCategory.SCHEMA

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        if ctx.source_model is None or ctx.target_model is None:
            return []
        comparator = SchemaComparator(
            mapping=ctx.mapping,
            source_type=ctx.source_type,
            target_type=ctx.target_type,
            target_capabilities=ctx.target_capabilities,
            result_factory=ctx.result_buffer,
        )
        return comparator.compare(ctx.source_model, ctx.target_model)
