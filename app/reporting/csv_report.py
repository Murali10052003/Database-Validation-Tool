"""CSV report renderer."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.reporting.report_builder import ValidationReport

_COLUMNS = [
    "check_id",
    "category",
    "status",
    "severity",
    "object_type",
    "source_object",
    "target_object",
    "source_value",
    "target_value",
    "differences",
    "message",
    "error",
    "duration_ms",
    "run_id", "classification", "validation_scope", "duration_scope", "coverage",
    "run_coverage", "started_at", "finished_at",
]


def render_csv(report: ValidationReport) -> str:
    """Render a report's results as CSV text (one row per validation result)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_COLUMNS)
    for r in report.results:
        writer.writerow(
            [
                r.check_id,
                r.category.value,
                r.status.value,
                r.severity.value,
                r.object_type or "",
                r.source_object or "",
                r.target_object or "",
                "" if r.source_value is None else r.source_value,
                "" if r.target_value is None else r.target_value,
                "; ".join(r.differences),
                r.message or "",
                r.error or "",
                "" if r.duration_ms is None else r.duration_ms,
                report.run_id or "Not recorded",
                r.classification or "Not recorded",
                r.validation_scope or "Not recorded",
                r.duration_scope or "Not recorded",
                r.coverage.model_dump_json() if r.coverage else "Not recorded",
                report.coverage.model_dump_json() if report.coverage else "Not recorded",
                report.started_at.isoformat() if report.started_at else "Not recorded",
                report.finished_at.isoformat() if report.finished_at else "Not recorded",
            ]
        )
    return buffer.getvalue()


def write_csv_report(report: ValidationReport, path: str | Path) -> Path:
    """Write a report as CSV to ``path`` (creating parent dirs) and return the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_csv(report), encoding="utf-8")
    return p
