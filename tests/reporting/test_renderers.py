"""HTML and CSV report renderers."""

from __future__ import annotations

from app.core.enums import Severity, ValidationCategory, ValidationProfile, ValidationStatus
from app.models.result import ValidationResult
from app.reporting.csv_report import render_csv
from app.reporting.html_report import render_html
from app.reporting.report_builder import ReportBuilder


def _report():
    results = [
        ValidationResult(
            check_id="schema:HR",
            category=ValidationCategory.SCHEMA,
            source_object="HR",
            status=ValidationStatus.PASS,
            severity=Severity.INFO,
        ),
        ValidationResult(
            check_id="row_count:HR.EMP",
            category=ValidationCategory.ROW_COUNT,
            source_object="HR.EMP",
            target_object="hr.emp",
            status=ValidationStatus.FAIL,
            severity=Severity.HIGH,
            source_value=100,
            target_value=90,
            differences=["row count mismatch: 100 vs 90"],
        ),
    ]
    return ReportBuilder().build("abc123", "HR migration", ValidationProfile.FULL, results)


def test_html_contains_summary_and_rows() -> None:
    html = render_html(_report())
    assert "<html" in html.lower()
    assert "HR migration" in html
    assert "OVERALL: FAIL" in html
    assert "row count mismatch: 100 vs 90" in html


def test_html_escapes_content() -> None:
    results = [
        ValidationResult(
            check_id="x",
            category=ValidationCategory.SCHEMA,
            source_object="<script>alert(1)</script>",
            status=ValidationStatus.PASS,
        )
    ]
    report = ReportBuilder().build("id", "m", ValidationProfile.QUICK, results)
    html = render_html(report)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_csv_has_header_and_one_row_per_result() -> None:
    csv_text = render_csv(_report())
    lines = [line for line in csv_text.splitlines() if line]
    assert lines[0].startswith("check_id,category,status,severity")
    assert len(lines) == 3  # header + 2 results
    assert "row count mismatch: 100 vs 90" in csv_text
