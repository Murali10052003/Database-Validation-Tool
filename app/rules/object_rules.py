"""Object-level naming rules.

Predictive checks over the *source* model. The most common cross-engine gotcha is
identifier length: Oracle allows 128 characters and MySQL 64, but PostgreSQL
truncates identifiers at 63 bytes — silently colliding names. This flags any
source identifier that exceeds the target engine's limit.
"""

from __future__ import annotations

from app.core.enums import DatabaseType, Severity, ValidationCategory, ValidationStatus
from app.models.database import DatabaseModel
from app.models.result import ValidationResult

# Maximum identifier length by target engine.
_MAX_IDENTIFIER = {
    DatabaseType.AZURE_POSTGRESQL: 63,
    DatabaseType.MYSQL: 64,
    DatabaseType.ORACLE: 128,
    DatabaseType.SQLSERVER: 128,
    DatabaseType.AZURE_SQL: 128,
}


def check_identifier_lengths(
    source: DatabaseModel, target_type: DatabaseType,
    *, results: list[ValidationResult] | None = None,
) -> list[ValidationResult]:
    """Flag source identifiers that exceed the target engine's identifier limit."""
    limit = _MAX_IDENTIFIER.get(target_type)
    if limit is None:
        return []
    results = results if results is not None else []
    for schema in source.schemas:
        for table in schema.tables:
            _check(results, table.name, f"{schema.name}.{table.name}", "TABLE", limit, target_type)
            for col in table.columns:
                fqn = f"{schema.name}.{table.name}.{col.name}"
                _check(results, col.name, fqn, "COLUMN", limit, target_type)
    return results


def _check(
    results: list[ValidationResult],
    name: str,
    fqn: str,
    object_type: str,
    limit: int,
    target_type: DatabaseType,
) -> None:
    if len(name) <= limit:
        return
    results.append(
        ValidationResult(
            check_id=f"object_rule:identifier:{fqn}",
            category=ValidationCategory.COMPATIBILITY,
            object_type=object_type,
            source_object=fqn,
            status=ValidationStatus.WARNING,
            severity=Severity.HIGH,
            differences=[
                f"identifier is {len(name)} chars; {target_type.value} truncates at {limit}"
            ],
        )
    )
