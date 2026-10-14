"""Report builder tests."""

from __future__ import annotations

import json

import pytest

from app.core.enums import (
    Severity,
    ValidationCategory,
    ValidationProfile,
    ValidationStatus,
)
from app.models.result import ValidationResult
from app.reporting.json_report import render_json
from app.reporting.report_builder import ReportBuilder


def _result(status: ValidationStatus) -> ValidationResult:
    return ValidationResult(
        check_id=f"c:{status.value}",
        category=ValidationCategory.SCHEMA,
        status=status,
        severity=Severity.INFO,
    )


def test_overall_fail_when_any_failure() -> None:
    results = [_result(ValidationStatus.PASS), _result(ValidationStatus.FAIL)]
    report = ReportBuilder().build("id1", "m", ValidationProfile.STANDARD, results)
    assert report.overall_status == ValidationStatus.FAIL
    assert report.summary.passed == 1
    assert report.summary.failed == 1


def test_overall_warning_when_only_warnings() -> None:
    results = [_result(ValidationStatus.PASS), _result(ValidationStatus.WARNING)]
    report = ReportBuilder().build("id2", "m", ValidationProfile.STANDARD, results)
    assert report.overall_status == ValidationStatus.WARNING


def test_overall_pass_when_all_pass() -> None:
    results = [_result(ValidationStatus.PASS)]
    report = ReportBuilder().build("id3", "m", ValidationProfile.STANDARD, results)
    assert report.overall_status == ValidationStatus.PASS


def test_error_forces_fail() -> None:
    results = [_result(ValidationStatus.PASS), _result(ValidationStatus.ERROR)]
    report = ReportBuilder().build("id4", "m", ValidationProfile.STANDARD, results)
    assert report.overall_status == ValidationStatus.FAIL


def test_json_render_is_valid_json() -> None:
    report = ReportBuilder().build("id5", "m", ValidationProfile.QUICK, [_result(ValidationStatus.PASS)])
    payload = json.loads(render_json(report))
    assert payload["migration_id"] == "id5"
    assert payload["summary"]["total"] == 1


@pytest.mark.parametrize("statuses", [
    [],
    [ValidationStatus.NOT_SUPPORTED],
    [ValidationStatus.SKIPPED],
    [ValidationStatus.PASS, ValidationStatus.NOT_SUPPORTED],
    [ValidationStatus.PASS, ValidationStatus.SKIPPED],
])
def test_incomplete_coverage_never_rolls_up_to_pass(statuses) -> None:
    report = ReportBuilder().build("incomplete", "m", ValidationProfile.FULL,
                                   [_result(status) for status in statuses])
    assert report.overall_status == ValidationStatus.WARNING


def test_failure_takes_precedence_over_incomplete_coverage() -> None:
    report = ReportBuilder().build("incomplete", "m", ValidationProfile.FULL,
                                   [_result(ValidationStatus.NOT_SUPPORTED), _result(ValidationStatus.FAIL)])
    assert report.overall_status == ValidationStatus.FAIL
