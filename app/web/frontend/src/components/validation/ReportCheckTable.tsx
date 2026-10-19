import { ArrowRight } from "lucide-react";
import type { ValidationResult } from "../../api/types";
import { CATEGORY_LABEL, categoryOf } from "./reportModel";
import { StatusPill } from "./parts";
import { reportValue } from "./reportValue";

export function ReportCheckTable({ checks, compact = false, onInspect }: {
  checks: ValidationResult[];
  compact?: boolean;
  onInspect: (result: ValidationResult) => void;
}) {
  return <div className="report-table-scroll" tabIndex={0} role="region" aria-label={compact ? "Priority findings" : "Check results"}>
    <table className={compact ? "report-table" : "report-table report-table--results"}>
      <thead><tr><th>Status</th><th>Object / Check</th>{!compact && <><th>Source</th><th>Target</th></>}<th>Finding</th><th><span className="report-visually-hidden">Actions</span></th></tr></thead>
      <tbody>{checks.length ? checks.map((result, index) => <tr key={`${result.check_id}-${index}`}>
        <td><StatusPill status={result.status} /></td>
        <td className="report-object"><strong>{result.source_object || result.target_object || result.check_id}</strong><small>{CATEGORY_LABEL[categoryOf(result)]} · {result.check_id}</small></td>
        {!compact && <><td><div className="report-value-preview">{reportValue(result.source_value)}</div></td><td><div className="report-value-preview">{reportValue(result.target_value)}</div></td></>}
        <td className="report-finding"><div className="report-value-preview">{result.error || result.differences?.join("; ") || result.message || "No finding recorded"}</div></td>
        <td><button type="button" className="report-link" aria-label={`Inspect ${result.source_object || result.target_object || result.check_id} ${result.check_id}`} onClick={() => onInspect(result)}>Inspect<ArrowRight size={14} /></button></td>
      </tr>) : <tr><td colSpan={compact ? 4 : 6} className="report-empty">No checks match this view.</td></tr>}</tbody>
    </table>
  </div>;
}