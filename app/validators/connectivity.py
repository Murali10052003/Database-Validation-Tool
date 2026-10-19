"""Connectivity validator."""

from __future__ import annotations

from app.core.enums import Severity, ValidationCategory, ValidationStatus
from app.models.database import ConnectionResult
from app.models.result import ValidationResult
from app.validators.base import ValidationContext, Validator


class ConnectivityValidator(Validator):
    """Verifies that both the source and target databases are reachable."""

    name = "connectivity"
    category = ValidationCategory.CONNECTIVITY

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        results = ctx.result_buffer()
        source = await ctx.source_adapter.test_connection()
        results.append(self._to_result("connectivity:source", "SOURCE", source))
        target = await ctx.target_adapter.test_connection()
        results.append(self._to_result("connectivity:target", "TARGET", target))
        return results

    @staticmethod
    def _to_result(check_id: str, side: str, conn: ConnectionResult) -> ValidationResult:
        status = ValidationStatus.PASS if conn.success else ValidationStatus.ERROR
        return ValidationResult(
            check_id=check_id,
            category=ValidationCategory.CONNECTIVITY,
            object_type=side,
            source_object=side,
            status=status,
            severity=Severity.CRITICAL if not conn.success else Severity.INFO,
            source_value=conn.version,
            duration_ms=int(conn.latency_ms) if conn.latency_ms is not None else None,
            error=conn.error,
            message=conn.message,
        )
