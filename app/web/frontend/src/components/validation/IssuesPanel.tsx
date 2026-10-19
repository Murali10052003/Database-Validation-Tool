// "Issues Requiring Attention" — FAIL / WARNING / ERROR results surfaced first,
// each with object, check type, source vs target and useful details. Reused for
// the Overview preview and the full Issues tab.

import { useMemo, useState } from "react";
import type { ValidationResult } from "../../api/types";
import { CATEGORY_LABEL, categoryOf, filterChecks } from "./reportModel";
import type { StatusFilter } from "./reportModel";
import { CheckLinks, SourceTargetDiff, StatusPill } from "./parts";
import { AlertIcon } from "../ui/icons";

export function IssueRow({ result }: { result: ValidationResult }) {
  const name = result.source_object || result.target_object || result.check_id;
  const nextAction = result.status === "ERROR"
    ? "Investigate the execution error and required connectivity or permissions before rerunning."
    : result.status === "NOT_SUPPORTED"
      ? "Arrange an independent check or add validated datatype support; this check is not a pass."
      : result.status === "SKIPPED"
        ? "Confirm the exclusion, missing target or configured limit is intentional before sign-off."
        : result.status === "FAIL"
          ? "Review the source/target difference and mapping, correct the mismatch, then rerun."
          : "Review this warning against the migration acceptance criteria.";
  return (
    <li className={`vr-issue vr-issue--${result.status.toLowerCase()}`}>
      <div className="vr-issue__head">
        <StatusPill status={result.status} />
        <span className="vr-issue__name" title={name ?? ""}>
          {name}
        </span>
        <span className="vr-issue__type">{CATEGORY_LABEL[categoryOf(result)]}</span>
        {result.severity && result.severity !== "INFO" && (
          <span className="vr-issue__sev">{result.severity}</span>
        )}
      </div>
      <SourceTargetDiff result={result} />
      <p className="vr-next-action"><strong>Next action:</strong> {nextAction}</p>
      <CheckLinks result={result} />
    </li>
  );
}

/** Compact preview used on the Overview tab. */
export function IssuesPreview({
  issues,
  limit = 5,
  onViewAll,
}: {
  issues: ValidationResult[];
  limit?: number;
  onViewAll: () => void;
}) {
  if (issues.length === 0) {
    return (
      <div className="vr-issues vr-issues--empty">
        <div className="vr-issues__ok">
          <span className="vr-issues__ok-badge">No emitted issues</span>
          No failures or coverage gaps in the emitted checks.
        </div>
      </div>
    );
  }

  const shown = issues.slice(0, limit);
  return (
    <div className="vr-issues">
      <ul className="vr-issue-list">
        {shown.map((r, i) => (
          <IssueRow key={`${r.check_id}-${i}`} result={r} />
        ))}
      </ul>
      <button type="button" className="btn btn--secondary btn--sm vr-issues__all" onClick={onViewAll}>
        View all issues ({issues.length})
      </button>
    </div>
  );
}

const ISSUE_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "FAILED", label: "Failed" },
  { id: "WARNING", label: "Warning" },
  { id: "ERROR", label: "Error" },
  { id: "SKIPPED", label: "Skipped" },
  { id: "NOT_SUPPORTED", label: "Not supported" },
];

/** Full, filterable issues list used on the Issues tab. */
export function IssuesPanel({ issues }: { issues: ValidationResult[] }) {
  const [filter, setFilter] = useState<StatusFilter>("ALL");
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");

  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: issues.length };
    c.FAILED = issues.filter((r) => r.status === "FAIL").length;
    c.WARNING = issues.filter((r) => r.status === "WARNING").length;
    c.ERROR = issues.filter((r) => r.status === "ERROR").length;
    c.SKIPPED = issues.filter((r) => r.status === "SKIPPED").length;
    c.NOT_SUPPORTED = issues.filter((r) => r.status === "NOT_SUPPORTED").length;
    return c;
  }, [issues]);

  const rows = filterChecks(issues, filter, query).filter((result) =>
    (!severity || result.severity === severity) && (!category || categoryOf(result) === category));

  if (issues.length === 0) {
    return (
      <div className="vr-issues vr-issues--empty">
        <div className="vr-issues__ok">
          <span className="vr-issues__ok-badge">No emitted issues</span>
          No failures or coverage gaps in the emitted checks.
        </div>
      </div>
    );
  }

  return (
    <div className="vr-issues">
      <div className="vr-toolbar">
        <select className="input" aria-label="Issue severity" value={severity} onChange={(event) => setSeverity(event.target.value)}>
          <option value="">All severities</option>{["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map((value) => <option key={value}>{value}</option>)}
        </select>
        <select className="input" aria-label="Issue category" value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">All categories</option>{[...new Set(issues.map(categoryOf))].map((value) => <option key={value} value={value}>{CATEGORY_LABEL[value]}</option>)}
        </select>
        <div className="vr-filters" role="group" aria-label="Filter issues by status">
          {ISSUE_FILTERS.filter((f) => f.id === "ALL" || counts[f.id] > 0).map((f) => (
            <button
              key={f.id}
              type="button"
              className={`chip ${filter === f.id ? "chip--active" : ""}`}
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
            >
              {f.label} · {counts[f.id]}
            </button>
          ))}
        </div>
        <input
          className="input input--sm vr-search"
          placeholder="Search object, table or column…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search issues"
        />
      </div>

      {rows.length === 0 ? (
        <div className="vr-empty">
          <AlertIcon size={18} /> No issues match the current filter.
        </div>
      ) : (
        <ul className="vr-issue-list">
          {rows.map((r, i) => (
            <IssueRow key={`${r.check_id}-${i}`} result={r} />
          ))}
        </ul>
      )}
    </div>
  );
}
