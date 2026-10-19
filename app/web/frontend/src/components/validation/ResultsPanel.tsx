import type { ValidationReport } from "../../api/types";
import { ReportDetails } from "./ReportDetails";

export function ResultsPanel({ report }: { report: ValidationReport }) {
  return <ReportDetails key={report.migration_id} report={report} />;
}