"""HTML report renderer.

Produces a self-contained (inline-CSS) HTML page so a report can be opened in a
browser or emailed without any external assets.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from app.core.enums import ValidationStatus
from app.reporting.report_builder import ValidationReport

_STATUS_COLORS = {
    ValidationStatus.PASS: "#16a34a",
    ValidationStatus.FAIL: "#dc2626",
    ValidationStatus.WARNING: "#d97706",
    ValidationStatus.SKIPPED: "#64748b",
    ValidationStatus.NOT_SUPPORTED: "#64748b",
    ValidationStatus.ERROR: "#e11d48",
}

_BODY_STYLE = (
    "font-family:system-ui,Segoe UI,Arial,sans-serif;"
    "margin:0;background:#f8fafc;color:#0f172a"
)


def render_html(report: ValidationReport) -> str:
    """Render a report as a standalone HTML document."""
    s = report.summary
    overall_color = _STATUS_COLORS.get(report.overall_status, "#334155")
    metrics = [
        ("Passed", s.passed, "#16a34a"),
        ("Failed", s.failed, "#dc2626"),
        ("Warning", s.warning, "#d97706"),
        ("Skipped", s.skipped, "#64748b"),
        ("Not supported", s.not_supported, "#64748b"),
        ("Error", s.error, "#e11d48"),
    ]
    metric_html = "".join(
        f'<div style="flex:1;min-width:110px;border:1px solid #e2e8f0;border-radius:10px;'
        f'padding:12px 16px;text-align:center">'
        f'<div style="font-size:26px;font-weight:700;color:{color}">{value}</div>'
        f'<div style="font-size:11px;text-transform:uppercase;color:#64748b;'
        f'letter-spacing:.5px">{escape(label)}</div></div>'
        for label, value, color in metrics
    )
    rank = {"ERROR": 0, "FAIL": 1, "WARNING": 2, "NOT_SUPPORTED": 3, "SKIPPED": 4, "PASS": 5}
    severity = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    ordered = sorted(report.results, key=lambda result: (
        rank[result.status.value], severity[result.severity.value],
    ))
    rows_html = "".join(_row_html(r) for r in ordered) or (
        '<tr><td colspan="5" style="padding:12px;color:#64748b">No results</td></tr>'
    )
    generated = report.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    evaluated = s.passed + s.failed + s.warning
    rate = f"{round(s.passed / evaluated * 100)}%" if evaluated else "Not evaluated"
    coverage = (escape(json.dumps(report.coverage.model_dump(), indent=2))
                if report.coverage else "Not recorded")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<title>Migration Validation Report · {escape(report.migration_name)}</title></head>
<body style="{_BODY_STYLE}">
<div style="max-width:1100px;margin:0 auto;padding:32px 24px">
  <h1 style="margin:0 0 4px">Migration Validation Report</h1>
  <p style="margin:0 0 4px;color:#475569">{escape(report.migration_name)}
     · profile <strong>{escape(report.profile.value)}</strong>
     · id <code>{escape(report.migration_id)}</code></p>
  <p style="margin:0 0 20px;color:#94a3b8;font-size:13px">Generated {escape(generated)}</p>
  <div style="display:inline-block;padding:8px 16px;border-radius:999px;color:#fff;
       font-weight:700;background:{overall_color};margin-bottom:20px">
    OVERALL: {escape(report.overall_status.value)}</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px">{metric_html}</div>
  <p>Pass rate: {rate} ({s.passed}/{evaluated} evaluated checks).
      Coverage: {evaluated}/{s.total} emitted checks evaluated.</p>
  <p>Run: {escape(report.run_id or 'Not recorded')}
      | Started: {escape(str(report.started_at or 'Not recorded'))}
      | Finished: {escape(str(report.finished_at or 'Not recorded'))}</p>
    <details><summary>Run coverage</summary>
        <pre style="white-space:pre-wrap;overflow-wrap:anywhere">{coverage}</pre></details>
  <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f0;
         border-radius:10px;overflow:hidden;font-size:13px">
    <thead><tr style="background:#f1f5f9;text-align:left">
      <th style="padding:10px 12px">Status</th><th style="padding:10px 12px">Category</th>
      <th style="padding:10px 12px">Severity</th><th style="padding:10px 12px">Object</th>
      <th style="padding:10px 12px">Detail</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div></body></html>"""


def _row_html(result) -> str:
    color = _STATUS_COLORS.get(result.status, "#334155")
    detail = "; ".join([*result.differences, *filter(None, [result.message, result.error])])
    coverage = (escape(result.coverage.model_dump_json(indent=2))
                if result.coverage else "Not recorded")
    values = escape(json.dumps({
        "source": result.source_value, "target": result.target_value,
    }, default=str))
    obj = result.source_object or result.target_object or result.check_id
    return (
        '<tr style="border-top:1px solid #e2e8f0">'
        f'<td style="padding:8px 12px;font-weight:700;color:{color}">'
        f"{escape(result.status.value)}</td>"
        f'<td style="padding:8px 12px">{escape(result.category.value)}</td>'
        f'<td style="padding:8px 12px">{escape(result.severity.value)}</td>'
        f'<td style="padding:8px 12px">{escape(str(obj))}</td>'
        f'<td style="padding:8px 12px;color:#475569;overflow-wrap:anywhere">{escape(str(detail))}'
        f'<p>{escape(result.validation_scope or "Scope not recorded")}</p><p>{values}</p>'
        f'<p>Duration: {result.duration_ms} ms '
        f'({escape(result.duration_scope or "scope not recorded")})</p>'
        '<details><summary>Data examined</summary>'
        f'<pre style="white-space:pre-wrap">{coverage}</pre></details></td></tr>'
    )


def write_html_report(report: ValidationReport, path: str | Path) -> Path:
    """Write a report as HTML to ``path`` (creating parent dirs) and return the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_html(report), encoding="utf-8")
    return p
