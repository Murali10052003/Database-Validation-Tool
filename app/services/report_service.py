"""Report persistence service.

Writes reports to (and locates them within) the configured report directory.
Phase 1 supports JSON; other formats plug in later.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.reporting.csv_report import render_csv
from app.reporting.html_report import render_html
from app.reporting.json_report import render_json, write_json_report
from app.reporting.report_builder import ValidationReport


class ReportService:
    """Saves and loads validation reports on disk."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def report_path(self, migration_id: str) -> Path:
        return Path(self._settings.report_dir) / f"migration-{migration_id}.json"

    def save_json(self, report: ValidationReport) -> Path:
        return write_json_report(report, self.report_path(report.migration_id))

    def load(self, migration_id: str) -> ValidationReport:
        path = self.report_path(migration_id)
        return ValidationReport.model_validate_json(path.read_text(encoding="utf-8"))

    def list_reports(self) -> list[ValidationReport]:
        """Load every saved report, newest first (best-effort; skips bad files)."""
        report_dir = Path(self._settings.report_dir)
        if not report_dir.is_dir():
            return []
        reports: list[ValidationReport] = []
        for path in report_dir.glob("migration-*.json"):
            try:
                reports.append(
                    ValidationReport.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except Exception:  # noqa: BLE001 - a malformed file must not break the list
                continue
        reports.sort(key=lambda r: r.generated_at, reverse=True)
        return reports

    @staticmethod
    def render(report: ValidationReport) -> str:
        return render_json(report)

    @staticmethod
    def render_html(report: ValidationReport) -> str:
        return render_html(report)

    @staticmethod
    def render_csv(report: ValidationReport) -> str:
        return render_csv(report)
