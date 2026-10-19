"""Report building and rendering.

The report builder aggregates :class:`ValidationResult` objects into a
:class:`ValidationReport` with summary counts and an overall status. Renderers turn
that report into concrete formats (JSON in Phase 1; HTML/CSV later).
"""

from app.reporting.json_report import render_json, write_json_report
from app.reporting.report_builder import (
    ReportBuilder,
    ValidationReport,
    ValidationSummary,
)

__all__ = [
    "ReportBuilder",
    "ValidationReport",
    "ValidationSummary",
    "render_json",
    "write_json_report",
]
