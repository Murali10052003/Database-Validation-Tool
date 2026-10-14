"""Aggregation of validation results into a report."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ValidationProfile, ValidationStatus
from app.models.database import DatabaseInfo
from app.models.result import ValidationResult


class ValidationSummary(BaseModel):
    """Counts of results by status."""

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    passed: int = 0
    failed: int = 0
    warning: int = 0
    skipped: int = 0
    not_supported: int = 0
    error: int = 0

    @classmethod
    def from_results(cls, results: list[ValidationResult]) -> ValidationSummary:
        counts = Counter(r.status for r in results)
        return cls(
            total=len(results),
            passed=counts.get(ValidationStatus.PASS, 0),
            failed=counts.get(ValidationStatus.FAIL, 0),
            warning=counts.get(ValidationStatus.WARNING, 0),
            skipped=counts.get(ValidationStatus.SKIPPED, 0),
            not_supported=counts.get(ValidationStatus.NOT_SUPPORTED, 0),
            error=counts.get(ValidationStatus.ERROR, 0),
        )


class RunCoverage(BaseModel):
    discovery_mode: str = "full"
    source_inventory_id: str | None = None
    target_inventory_id: str | None = None
    mapping_version_id: str | None = None
    metadata_warning: str | None = None
    selected_stages: list[str] = Field(default_factory=list)
    not_selected_stages: list[str] = Field(default_factory=list)
    reached_stages: list[str] = Field(default_factory=list)
    not_reached_stages: list[str] = Field(default_factory=list)
    included_objects: list[str] = Field(default_factory=list)
    excluded_objects: list[str] = Field(default_factory=list)
    schema_options: dict[str, bool] = Field(default_factory=dict)
    sample_limit: int | None = None
    checksum_limit: int
    snapshot_consistent: bool = False


class ValidationReport(BaseModel):
    """A complete, serializable validation report."""

    model_config = ConfigDict(extra="forbid")

    migration_id: str
    migration_name: str
    generated_at: datetime
    profile: ValidationProfile
    source: DatabaseInfo | None = None
    target: DatabaseInfo | None = None
    summary: ValidationSummary
    overall_status: ValidationStatus
    duration_ms: int | None = None
    results: list[ValidationResult] = Field(default_factory=list)
    run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    coverage: RunCoverage | None = None


class ReportBuilder:
    """Builds a :class:`ValidationReport` from results."""

    def build(
        self,
        migration_id: str,
        migration_name: str,
        profile: ValidationProfile,
        results: list[ValidationResult],
        source: DatabaseInfo | None = None,
        target: DatabaseInfo | None = None,
        duration_ms: int | None = None,
    ) -> ValidationReport:
        summary = ValidationSummary.from_results(results)
        return ValidationReport(
            migration_id=migration_id,
            migration_name=migration_name,
            generated_at=datetime.now(UTC),
            profile=profile,
            source=source,
            target=target,
            summary=summary,
            overall_status=self._overall_status(summary),
            duration_ms=duration_ms,
            results=results,
        )

    @staticmethod
    def _overall_status(summary: ValidationSummary) -> ValidationStatus:
        """Only complete, nonempty, all-passing reports receive PASS."""
        if summary.failed > 0 or summary.error > 0:
            return ValidationStatus.FAIL
        if summary.warning or summary.not_supported or summary.skipped or not summary.total:
            return ValidationStatus.WARNING
        return ValidationStatus.PASS
