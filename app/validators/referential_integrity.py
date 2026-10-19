"""Referential-integrity (orphan-row) validation.

For every foreign key discovered on the target, counts child rows whose non-null FK
value has no matching parent row. Orphans indicate data migrated out of referential
order or with broken relationships. Runs against the target database only.
"""

from __future__ import annotations

from app.core.enums import Severity, ValidationCategory, ValidationStatus
from app.models.constraint import ConstraintModel, ConstraintType
from app.models.result import ValidationResult
from app.models.schema import SchemaModel
from app.models.table import TableModel
from app.validators.base import ValidationContext, Validator


class ReferentialIntegrityValidator(Validator):
    """Detects orphan rows against target foreign keys."""

    name = "referential_integrity"
    category = ValidationCategory.REFERENTIAL_INTEGRITY

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        if ctx.target_model is None or not ctx.target_capabilities.foreign_keys:
            return []
        included_targets: set[tuple[str, str]] | None = None
        if (any(name.strip() for name in ctx.config.mapping.included_objects)
            or ctx.config.mapping.excluded_objects
            or ctx.config.discovery_mode != "full"):
            included_targets = {
                tuple(
                    name.casefold() for name in ctx.mapping.resolve_table(schema.name, table.name)
                )
                for schema in (ctx.source_model.schemas if ctx.source_model else [])
                for table in schema.tables
                if not ctx.mapping.is_excluded_table(schema.name, table.name)
            }
        results = ctx.result_buffer()
        for schema in ctx.target_model.schemas:
            for table in schema.tables:
                if included_targets is not None and (
                    schema.name.casefold(), table.name.casefold()
                ) not in included_targets:
                    continue
                for con in table.constraints:
                    if con.constraint_type is not ConstraintType.FOREIGN_KEY:
                        continue
                    if con.references is None or not con.references.ref_columns:
                        continue
                    results.append(await self._check_fk(ctx, schema, table, con))
        return results

    async def _check_fk(
        self,
        ctx: ValidationContext,
        schema: SchemaModel,
        table: TableModel,
        con: ConstraintModel,
    ) -> ValidationResult:
        references = con.references
        assert references is not None  # guarded by the caller
        fqn = f"{schema.name}.{table.name}"
        ref_fqn = f"{references.ref_schema or schema.name}.{references.ref_table}"
        check_id = f"referential_integrity:{fqn}.{con.name}"
        try:
            orphans = await ctx.target_adapter.run_bounded(
                ctx.config.validation.data.timeout_seconds,
                lambda: ctx.target_adapter.count_orphans(
                    schema.name,
                    table.name,
                    con.columns,
                    references.ref_schema or schema.name,
                    references.ref_table,
                    references.ref_columns,
                ),
                f"Orphan count of {fqn} ({con.name})",
            )
        except Exception as exc:
            return ValidationResult(
                check_id=check_id,
                category=ValidationCategory.REFERENTIAL_INTEGRITY,
                object_type="FOREIGN_KEY",
                target_object=fqn,
                status=ValidationStatus.ERROR,
                severity=Severity.HIGH,
                error=str(exc),
            )
        matched = orphans == 0
        return ValidationResult(
            check_id=check_id,
            category=ValidationCategory.REFERENTIAL_INTEGRITY,
            object_type="FOREIGN_KEY",
            target_object=f"{fqn} -> {ref_fqn}",
            status=ValidationStatus.PASS if matched else ValidationStatus.FAIL,
            severity=Severity.INFO if matched else Severity.CRITICAL,
            target_value=orphans,
            differences=[] if matched else [f"{orphans} orphan row(s) violate {ref_fqn}"],
        )
