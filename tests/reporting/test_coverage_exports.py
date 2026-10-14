import csv
import io
import json

from app.models.result import CheckCoverage, ValidationResult
from app.reporting.csv_report import render_csv
from app.reporting.html_report import render_html
from app.reporting.report_builder import ReportBuilder


def test_exports_retain_incomplete_coverage_and_values():
    result = ValidationResult(
        check_id="checksum:HR.T", category="CHECKSUM", status="SKIPPED",
        source_value="<private>", message="Cap exceeded",
        coverage=CheckCoverage(mode="checksum", limit=2, capped=True, source_rows_fetched=3),
    )
    report = ReportBuilder().build("a" * 12, "Example", "full", [result])
    row = next(csv.DictReader(io.StringIO(render_csv(report))))
    coverage = json.loads(row["coverage"])
    assert row["status"] == "SKIPPED"
    assert coverage["source_rows_fetched"] == 3
    assert coverage["target_rows_fetched"] is None
    assert row["run_coverage"] == "Not recorded"
    html = render_html(report)
    assert "Not evaluated" in html
    assert "Cap exceeded" in html
    assert "&lt;private&gt;" in html
    assert "source_rows_fetched" in html


def test_old_report_exports_do_not_invent_coverage():
    result = ValidationResult(check_id="old", category="COLUMN", status="PASS")
    report = ReportBuilder().build("b" * 12, "Old", "quick", [result])
    row = next(csv.DictReader(io.StringIO(render_csv(report))))
    assert row["coverage"] == "Not recorded"
    assert row["started_at"] == "Not recorded"