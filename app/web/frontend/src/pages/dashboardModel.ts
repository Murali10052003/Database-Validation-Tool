import type { ReportListItem, ValidationReport, ValidationStatus } from "../api/types";

export const dashboardStatusLabels: Record<ValidationStatus, string> = {
  PASS: "Passed",
  FAIL: "Failed",
  WARNING: "Needs review",
  ERROR: "Execution error",
  SKIPPED: "Skipped",
  NOT_SUPPORTED: "Not supported",
};

export function dashboardStatus(report: ReportListItem | ValidationReport): ValidationStatus {
  const counts = "summary" in report ? report.summary : report;
  if (report.overall_status === "ERROR" || ("error" in counts && counts.error > 0)) return "ERROR";
  if (report.overall_status === "FAIL" || counts.failed > 0) return "FAIL";
  if (
    counts.total === 0 || counts.warning > 0 ||
    ("skipped" in counts && (counts.skipped > 0 || counts.not_supported > 0)) ||
    ("coverage" in report && report.coverage?.not_reached_stages.length)
  ) return "WARNING";
  return report.overall_status;
}

export function newestReports(reports: ReportListItem[]): ReportListItem[] {
  return [...reports].sort((first, second) =>
    (Date.parse(second.generated_at) || 0) - (Date.parse(first.generated_at) || 0));
}