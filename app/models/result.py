"""Canonical validation result model (spec Section 21)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Severity, ValidationCategory, ValidationStatus


class CheckCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    source_rows_fetched: int | None = None
    target_rows_fetched: int | None = None
    source_rows_reported: int | None = None
    target_rows_reported: int | None = None
    rows_compared: int | None = None
    source_rows_hashed: int | None = None
    target_rows_hashed: int | None = None
    limit: int | None = None
    capped: bool = False
    source_complete: bool | None = None
    target_complete: bool | None = None
    source_columns: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    omitted_source_columns: list[str] = Field(default_factory=list)
    source_order: list[str] = Field(default_factory=list)
    target_order: list[str] = Field(default_factory=list)
    snapshot_consistent: bool = False
    checksum_format: str | None = None
    # Row counts: True when that side's value is a statistics estimate, not an exact count.
    source_estimated: bool | None = None
    target_estimated: bool | None = None


class ValidationResult(BaseModel):
    """The outcome of a single validation check."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    category: ValidationCategory
    object_type: str | None = None
    source_object: str | None = None
    target_object: str | None = None
    status: ValidationStatus
    severity: Severity = Severity.MEDIUM
    source_value: Any | None = None
    target_value: Any | None = None
    differences: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    error: str | None = None
    message: str | None = None
    coverage: CheckCoverage | None = None
    classification: Literal["column_attributes", "datatype", "execution"] | None = None
    validation_scope: str | None = None
    duration_scope: str | None = None

    @classmethod
    def passed(cls, check_id: str, category: ValidationCategory, **kwargs: Any) -> ValidationResult:
        """Convenience constructor for a PASS result."""
        return cls(check_id=check_id, category=category, status=ValidationStatus.PASS, **kwargs)

    @classmethod
    def failed(
        cls,
        check_id: str,
        category: ValidationCategory,
        differences: list[str] | None = None,
        severity: Severity = Severity.HIGH,
        **kwargs: Any,
    ) -> ValidationResult:
        """Convenience constructor for a FAIL result."""
        return cls(
            check_id=check_id,
            category=category,
            status=ValidationStatus.FAIL,
            severity=severity,
            differences=differences or [],
            **kwargs,
        )
