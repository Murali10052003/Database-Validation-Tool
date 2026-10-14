// Small presentational building blocks shared across the report views.

import type { ValidationResult, ValidationStatus } from "../../api/types";
import type { GroupStatus } from "./reportModel";
import { createContext, useContext } from "react";

export const ReportNavigation = createContext<{
  runId?: string | null;
  openCheck?: (result: ValidationResult) => void;
}>({});

export function CheckLinks({ result }: { result: ValidationResult }) {
  const navigation = useContext(ReportNavigation);
  if (!navigation.runId) return null;
  return <div className="vr-check-links">
    {navigation.runId && <a href={`#/logs?run=${encodeURIComponent(navigation.runId)}&query=${encodeURIComponent(result.check_id)}`}>Run logs</a>}
  </div>;
}

const PILL_CLASS: Record<string, string> = {
  PASS: "vr-pill--pass",
  FAIL: "vr-pill--fail",
  ERROR: "vr-pill--error",
  WARNING: "vr-pill--warning",
  SKIPPED: "vr-pill--skipped",
  NOT_SUPPORTED: "vr-pill--skipped",
};

const PILL_LABEL: Record<string, string> = {
  PASS: "Pass",
  FAIL: "Fail",
  ERROR: "Error",
  WARNING: "Warning",
  SKIPPED: "Skipped",
  NOT_SUPPORTED: "Not supported",
};

export function StatusPill({
  status,
  className = "",
}: {
  status: ValidationStatus | GroupStatus;
  className?: string;
}) {
  return (
    <span className={`vr-pill ${PILL_CLASS[status] ?? "vr-pill--skipped"} ${className}`}>
      {PILL_LABEL[status] ?? status}
    </span>
  );
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * Side-by-side source vs target comparison for a failing/warning check.
 * Falls back gracefully when a value or difference list is absent.
 */
export function SourceTargetDiff({ result }: { result: ValidationResult }) {
  const hasValues =
    result.source_value !== null && result.source_value !== undefined
      ? true
      : result.target_value !== null && result.target_value !== undefined;
  const differences = result.differences ?? [];

  return (
    <div className="vr-diff">
      {hasValues && (
        <div className="vr-diff__grid">
          <div className="vr-diff__cell vr-diff__cell--source">
            <span className="vr-diff__label">Source</span>
            <code className="vr-diff__value">{displayValue(result.source_value)}</code>
          </div>
          <span className="vr-diff__arrow" aria-hidden>
            →
          </span>
          <div className="vr-diff__cell vr-diff__cell--target">
            <span className="vr-diff__label">Target</span>
            <code className="vr-diff__value">{displayValue(result.target_value)}</code>
          </div>
        </div>
      )}
      {differences.length > 0 && (
        <ul className="vr-diff__list">
          {differences.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      )}
      {result.message && <p className="vr-diff__note">{result.message}</p>}
      {result.error && <p className="vr-diff__note">{result.error}</p>}
    </div>
  );
}

const HEALTH_TONE: Record<GroupStatus, string> = {
  PASS: "vr-health__bar--pass",
  FAIL: "vr-health__bar--fail",
  ERROR: "vr-health__bar--fail",
  WARNING: "vr-health__bar--warning",
  SKIPPED: "vr-health__bar--skipped",
  NOT_SUPPORTED: "vr-health__bar--skipped",
};

export function HealthBar({
  value,
  status,
  label,
}: {
  value: number | null;
  status: GroupStatus;
  label?: string;
}) {
  if (value === null) return <span className="vr-not-evaluated">Not evaluated</span>;
  return (
    <div
      className="vr-health"
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? `Health ${value}%`}
    >
      <div className={`vr-health__bar ${HEALTH_TONE[status]}`} style={{ width: `${value}%` }} />
    </div>
  );
}
