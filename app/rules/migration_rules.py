"""Migration-specific rules: unsupported-feature detection.

Predictive checks that compare *source* features against the target's declared
capabilities, so gaps surface even before the target schema is built (e.g. a source
that relies on materialized views or sequences the target engine cannot represent).
"""

from __future__ import annotations

from app.core.enums import Severity, ValidationCategory, ValidationStatus
from app.models.capabilities import DatabaseCapabilities
from app.models.database import DatabaseModel
from app.models.result import ValidationResult


def check_unsupported_features(
    source: DatabaseModel, target_capabilities: DatabaseCapabilities,
    *, results: list[ValidationResult] | None = None,
) -> list[ValidationResult]:
    """Flag source features the target engine cannot represent."""
    results = results if results is not None else []
    caps = target_capabilities
    for schema in source.schemas:
        if not caps.sequences and schema.sequences:
            results.append(
                _finding(
                    f"migration_rule:sequences:{schema.name}",
                    f"{schema.name} ({len(schema.sequences)} sequences)",
                    "target does not support sequences; convert to identity/auto-increment",
                )
            )
        if not caps.materialized_views:
            mviews = [v for v in schema.views if v.materialized]
            if mviews:
                results.append(
                    _finding(
                        f"migration_rule:matviews:{schema.name}",
                        f"{schema.name} ({len(mviews)} materialized views)",
                        "target does not support materialized views",
                    )
                )
        if not caps.identity_columns:
            for table in schema.tables:
                identity_cols = [c for c in table.columns if c.is_identity]
                if identity_cols:
                    fqn = f"{schema.name}.{table.name}"
                    results.append(
                        _finding(
                            f"migration_rule:identity:{fqn}",
                            f"{fqn} ({len(identity_cols)} identity columns)",
                            "target does not support identity columns",
                        )
                    )
    return results


def _finding(check_id: str, source_object: str, message: str) -> ValidationResult:
    return ValidationResult(
        check_id=check_id,
        category=ValidationCategory.COMPATIBILITY,
        source_object=source_object,
        status=ValidationStatus.WARNING,
        severity=Severity.MEDIUM,
        differences=[message],
    )
