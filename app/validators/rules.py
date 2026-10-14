"""Migration-rules validator.

Runs the predictive rule engines (type compatibility, identifier limits, and
unsupported-feature detection) over the discovered source model. These are advisory
warnings that surface migration risks independent of the target's current state.
"""

from __future__ import annotations

from app.core.enums import ValidationCategory
from app.models.result import ValidationResult
from app.rules.compatibility import check_type_compatibility
from app.rules.migration_rules import check_unsupported_features
from app.rules.object_rules import check_identifier_lengths
from app.validators.base import ValidationContext, Validator


class RulesValidator(Validator):
    """Applies cross-database migration rules to the source model."""

    name = "rules"
    category = ValidationCategory.COMPATIBILITY

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        if ctx.source_model is None:
            return []
        source_model = ctx.source_model
        if any(name.strip() for name in ctx.config.mapping.included_objects):
            source_model = source_model.model_copy(update={
                "schemas": [
                    schema.model_copy(update={
                        field: [
                            obj for obj in getattr(schema, field)
                            if not ctx.mapping.is_excluded_table(schema.name, obj.name)
                        ]
                        for field in ("tables", "sequences", "views", "routines")
                    })
                    for schema in source_model.schemas
                    if not ctx.mapping.is_excluded_schema(schema.name)
                ],
            })
        results = ctx.result_buffer()
        check_type_compatibility(source_model, ctx.target_type, results=results)
        check_identifier_lengths(source_model, ctx.target_type, results=results)
        check_unsupported_features(source_model, ctx.target_capabilities, results=results)
        return results
