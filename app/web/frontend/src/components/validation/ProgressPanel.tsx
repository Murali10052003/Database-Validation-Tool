import type { ValidationProfileName } from "../../api/types";

const STAGES: Record<ValidationProfileName, string[]> = {
  custom: ["Connectivity", "Discovery", "Selected checks"],
  quick: ["Connectivity", "Schema", "Tables", "Row counts"],
  standard: [
    "Connectivity",
    "Schema",
    "Tables",
    "Columns",
    "Constraints",
    "Indexes",
    "Rules",
    "Null counts",
  ],
  full: [
    "Connectivity",
    "Schema",
    "Tables",
    "Columns",
    "Constraints",
    "Indexes",
    "Sequences",
    "Views",
    "Aggregates",
    "Checksums",
    "Referential integrity",
  ],
};

interface Props {
  running: boolean;
  done: boolean;
  success: boolean;
  profile: ValidationProfileName;
}

export function ProgressPanel({ running, done, success, profile }: Props) {
  const label = running
    ? "Running validation…"
    : done
      ? success
        ? "Validation complete"
        : "Validation failed"
      : "Idle";

  return (
    <div className={`progress ${running ? "progress--running" : ""} ${done && !success ? "progress--fail" : ""}`}>
      <div className="progress__label">{label}</div>
      <div className="progress__bar">
        <div className="progress__fill" />
      </div>
      <div className="progress__stages">
        {STAGES[profile].map((s) => (
          <span key={s} className={`stage-chip ${done ? "stage-chip--done" : ""}`}>
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}
