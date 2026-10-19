"""Cross-database type-compatibility rules.

Predictive checks over the *source* model: flags columns whose logical type has no
clean mapping (``UNKNOWN``), which typically require a manual type decision during
migration. Independent of the target's discovered state.
"""

from __future__ import annotations

from app.core.enums import DatabaseType, LogicalType, Severity, ValidationCategory, ValidationStatus
from app.models.database import DatabaseModel
from app.models.result import ValidationResult


def check_type_compatibility(
    source: DatabaseModel, target_type: DatabaseType,
    *, results: list[ValidationResult] | None = None,
) -> list[ValidationResult]:
    """Flag source columns whose logical type is unknown/unmapped for the target."""
    results = results if results is not None else []
    for schema in source.schemas:
        for table in schema.tables:
            for col in table.columns:
                if col.logical_type is not LogicalType.UNKNOWN:
                    continue
                fqn = f"{schema.name}.{table.name}.{col.name}"
                results.append(
                    ValidationResult(
                        check_id=f"compatibility:type:{fqn}",
                        category=ValidationCategory.COMPATIBILITY,
                        object_type="COLUMN",
                        source_object=f"{fqn} ({col.native_type})",
                        status=ValidationStatus.WARNING,
                        severity=Severity.MEDIUM,
                        differences=[
                            f"type {col.native_type!r} has no canonical mapping for "
                            f"{target_type.value}; verify the target type manually"
                        ],
                    )
                )
    return results
