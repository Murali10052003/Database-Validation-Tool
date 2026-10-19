"""JSON report renderer."""

from __future__ import annotations

from pathlib import Path

from app.reporting.report_builder import ValidationReport


def render_json(report: ValidationReport, *, indent: int = 2) -> str:
    """Render a report as a JSON string."""
    return report.model_dump_json(indent=indent)


def write_json_report(report: ValidationReport, path: str | Path) -> Path:
    """Write a report to ``path`` (creating parent dirs) and return the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_json(report), encoding="utf-8")
    return p
