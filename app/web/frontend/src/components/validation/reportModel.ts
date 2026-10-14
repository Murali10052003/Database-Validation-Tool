// Pure, framework-free view model for the validation report.
//
// This layer only *reshapes* the results returned by the API into a hierarchy
// the UI can render (Category -> Object -> Check). It never invents results or
// mutates migration logic — every check shown maps 1:1 to a real
// `ValidationResult` from the backend.

import type {
  ValidationReport,
  ValidationResult,
  ValidationStatus,
} from "../../api/types";

export type DisplayCategoryId =
  | "schema"
  | "tables"
  | "columns"
  | "dataTypes"
  | "constraints"
  | "indexes"
  | "sequences"
  | "otherObjects"
  | "views" | "routines" | "triggers" | "partitions" | "samples" | "custom" | "compatibility" | "execution"
  | "rowCounts"
  | "nullCounts"
  | "aggregates"
  | "checksums"
  | "integrity";

export type DetailTabId = "structure" | "data" | "integrity" | "execution";
export type TabId = "overview" | DetailTabId | "issues";

/** A coarse status used for badges/health of an aggregated group. */
export type GroupStatus = ValidationStatus;

export type StatusFilter =
  | "ALL"
  | "FAILED"
  | "WARNING"
  | "PASSED"
  | "SKIPPED"
  | "NOT_SUPPORTED"
  | "ERROR";

export interface CategoryMeta {
  id: DisplayCategoryId;
  label: string;
  tab: DetailTabId;
  description: string;
}

// Order defines both the Overview card grid and the per-tab section order.
export const CATEGORY_META: CategoryMeta[] = [
  { id: "schema", label: "Schema", tab: "structure", description: "Schema presence & mapping" },
  { id: "tables", label: "Tables", tab: "structure", description: "Table presence" },
  { id: "columns", label: "Columns", tab: "structure", description: "Column presence & attributes" },
  { id: "dataTypes", label: "Data Types", tab: "structure", description: "Column type compatibility" },
  { id: "constraints", label: "Constraints", tab: "structure", description: "Keys & constraints" },
  { id: "indexes", label: "Indexes", tab: "structure", description: "Index definitions" },
  { id: "sequences", label: "Sequences / Identity", tab: "structure", description: "Sequences & identity" },
  { id: "otherObjects", label: "Unclassified Checks", tab: "execution", description: "Unrecognized categories" },
  { id: "views", label: "Views", tab: "structure", description: "View checks" },
  { id: "routines", label: "Routines", tab: "structure", description: "Routine checks" },
  { id: "triggers", label: "Triggers", tab: "structure", description: "Trigger checks" },
  { id: "partitions", label: "Partitions", tab: "structure", description: "Partition checks" },
  { id: "samples", label: "Sample Data", tab: "data", description: "Bounded sample comparison" },
  { id: "custom", label: "Custom Queries", tab: "integrity", description: "Configured assertions" },
  { id: "compatibility", label: "Compatibility Rules", tab: "integrity", description: "Migration advisories" },
  { id: "execution", label: "Execution", tab: "execution", description: "Connectivity and discovery" },
  { id: "rowCounts", label: "Row Counts", tab: "data", description: "Table row counts" },
  { id: "nullCounts", label: "NULL Counts", tab: "data", description: "Per-column NULL counts" },
  { id: "aggregates", label: "Aggregates", tab: "data", description: "Numeric aggregates" },
  { id: "checksums", label: "Checksums", tab: "data", description: "Checksums subject to configured cap" },
  { id: "integrity", label: "Referential Integrity", tab: "integrity", description: "Orphan-row checks" },
];

export const CATEGORY_LABEL: Record<DisplayCategoryId, string> = CATEGORY_META.reduce(
  (acc, m) => ({ ...acc, [m.id]: m.label }),
  {} as Record<DisplayCategoryId, string>,
);

const DETAIL_LABEL: Record<DisplayCategoryId, string> = {
  schema: "Schema",
  tables: "Table",
  columns: "Column",
  dataTypes: "Data type",
  constraints: "Constraint",
  indexes: "Index",
  sequences: "Sequence",
  otherObjects: "Object",
  views: "View", routines: "Routine", triggers: "Trigger", partitions: "Partition",
  samples: "Sample", custom: "Query", compatibility: "Rule", execution: "Stage",
  rowCounts: "Row count",
  nullCounts: "NULL count",
  aggregates: "Aggregate",
  checksums: "Checksum",
  integrity: "Referential integrity",
};

const TYPE_DIFF = /\b(type|precision|scale|length)\b/i;

function isTypeDifference(r: ValidationResult): boolean {
  return (r.differences ?? []).some((d) => TYPE_DIFF.test(d));
}

/**
 * Map a backend `ValidationCategory` onto one display category. The mapping is a
 * clean partition (every result lands in exactly one bucket) so category totals
 * always sum to the report total.
 *
 * The backend emits a single COLUMN check per column that compares both the data
 * type and structural attributes. A failing/erroring column whose difference is
 * type/precision/scale/length related is surfaced under "Data Types" so type
 * conversion risks are easy to find; everything else stays under "Columns".
 */
export function categoryOf(r: ValidationResult): DisplayCategoryId {
  if (r.classification === "execution") return "execution";
  if (r.classification === "datatype") return "dataTypes";
  if (r.classification === "column_attributes") return "columns";
  if (r.check_id === "discovery") return "execution";
  switch (r.category) {
    case "VIEW": return "views";
    case "ROUTINE": return "routines";
    case "TRIGGER": return "triggers";
    case "PARTITION": return "partitions";
    case "SAMPLE_DATA": return "samples";
    case "CUSTOM_QUERY": return "custom";
    case "COMPATIBILITY": return "compatibility";
    case "CONNECTIVITY": return "execution";
    case "SCHEMA":
      return "schema";
    case "TABLE":
      return "tables";
    case "COLUMN":
      return r.status !== "PASS" && isTypeDifference(r) ? "dataTypes" : "columns";
    case "CONSTRAINT":
      return "constraints";
    case "INDEX":
      return "indexes";
    case "SEQUENCE":
      return "sequences";
    case "ROW_COUNT":
      return "rowCounts";
    case "NULL_COUNT":
      return "nullCounts";
    case "AGGREGATE":
      return "aggregates";
    case "CHECKSUM":
      return "checksums";
    case "REFERENTIAL_INTEGRITY":
      return "integrity";
    default:
      // VIEW, ROUTINE, TRIGGER, PARTITION, CUSTOM_QUERY, COMPATIBILITY,
      // SAMPLE_DATA, CONNECTIVITY, and any future category.
      return "otherObjects";
  }
}

export interface Counts {
  total: number;
  passed: number;
  failed: number;
  warning: number;
  skipped: number;
  error: number;
  notSupported: number;
}

function emptyCounts(): Counts {
  return { total: 0, passed: 0, failed: 0, warning: 0, skipped: 0, error: 0, notSupported: 0 };
}

function tally(results: ValidationResult[]): Counts {
  const c = emptyCounts();
  for (const r of results) {
    c.total += 1;
    switch (r.status) {
      case "PASS":
        c.passed += 1;
        break;
      case "FAIL":
        c.failed += 1;
        break;
      case "WARNING":
        c.warning += 1;
        break;
      case "SKIPPED":
        c.skipped += 1;
        break;
      case "NOT_SUPPORTED":
        c.notSupported += 1;
        break;
      case "ERROR":
        c.error += 1;
        break;
    }
  }
  return c;
}

export function groupStatus(c: Counts): GroupStatus {
  if (c.error) return "ERROR";
  if (c.failed) return "FAIL";
  if (c.warning) return "WARNING";
  if (c.passed && (c.skipped || c.notSupported)) return "WARNING";
  if (c.passed) return "PASS";
  if (c.notSupported) return "NOT_SUPPORTED";
  return "SKIPPED";
}

/** passed / (checks that could pass) as a 0-100 integer. */
export function healthPct(c: Counts): number | null {
  const relevant = c.passed + c.failed + c.warning;
  if (!relevant) return null;
  return Math.round((c.passed / relevant) * 100);
}

export interface ObjectGroup {
  key: string;
  label: string;
  checks: ValidationResult[];
  counts: Counts;
  status: GroupStatus;
}

export interface CategoryGroup {
  meta: CategoryMeta;
  checks: ValidationResult[];
  objects: ObjectGroup[];
  counts: Counts;
  status: GroupStatus;
  health: number | null;
}

export interface ReportModel {
  categories: CategoryGroup[];
  issues: ValidationResult[];
  counts: Counts;
  score: number | null;
}

function cleanName(name: string): string {
  return name.replace(/\s*\(.*\)\s*$/, "").trim();
}

/** Parent object a check belongs to (e.g. a column's table). */
function objectKeyFor(r: ValidationResult): string {
  const raw = r.source_object || r.target_object || r.check_id || "—";
  const clean = cleanName(raw);
  const parts = clean.split(".");
  if (parts.length >= 3) return parts.slice(0, 2).join(".");
  return clean;
}

export function checkLabel(r: ValidationResult): string {
  const raw = r.source_object || r.target_object || r.check_id || "—";
  const clean = cleanName(raw);
  const key = objectKeyFor(r);
  if (clean === key) return DETAIL_LABEL[categoryOf(r)];
  const parts = clean.split(".");
  return parts[parts.length - 1];
}

const STATUS_RANK: Record<ValidationStatus, number> = {
  ERROR: 5,
  FAIL: 4,
  WARNING: 3,
  NOT_SUPPORTED: 2,
  SKIPPED: 1,
  PASS: 0,
};

const SEVERITY_RANK: Record<string, number> = {
  CRITICAL: 5,
  HIGH: 4,
  MEDIUM: 3,
  LOW: 2,
  INFO: 1,
};

function buildObjects(checks: ValidationResult[]): ObjectGroup[] {
  const byKey = new Map<string, ValidationResult[]>();
  for (const r of checks) {
    const key = objectKeyFor(r);
    const list = byKey.get(key);
    if (list) list.push(r);
    else byKey.set(key, [r]);
  }
  const groups: ObjectGroup[] = [];
  for (const [key, list] of byKey) {
    const counts = tally(list);
    groups.push({ key, label: key, checks: list, counts, status: groupStatus(counts) });
  }
  // Surface problem objects first, then alphabetical for stable scanning.
  groups.sort((a, b) => {
    const sa = STATUS_RANK[worstStatus(a.status)] ?? 0;
    const sb = STATUS_RANK[worstStatus(b.status)] ?? 0;
    if (sa !== sb) return sb - sa;
    return a.label.localeCompare(b.label);
  });
  return groups;
}

function worstStatus(g: GroupStatus): ValidationStatus {
  return g === "SKIPPED" ? "SKIPPED" : (g as ValidationStatus);
}

export function buildReportModel(report: ValidationReport): ReportModel {
  const buckets = new Map<DisplayCategoryId, ValidationResult[]>();
  for (const r of report.results) {
    const id = categoryOf(r);
    const list = buckets.get(id);
    if (list) list.push(r);
    else buckets.set(id, [r]);
  }

  const categories: CategoryGroup[] = CATEGORY_META.filter(
    (meta) => !["samples", "custom"].includes(meta.id) || buckets.has(meta.id),
  ).map((meta) => {
    const checks = buckets.get(meta.id) ?? [];
    const counts = tally(checks);
    return {
      meta,
      checks,
      objects: buildObjects(checks),
      counts,
      status: groupStatus(counts),
      health: healthPct(counts),
    };
  });

  const issues = report.results
    .filter((r) => r.status !== "PASS")
    .sort((a, b) => {
      const s = STATUS_RANK[b.status] - STATUS_RANK[a.status];
      if (s !== 0) return s;
      const sev = (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0);
      if (sev !== 0) return sev;
      const an = a.source_object || a.target_object || a.check_id || "";
      const bn = b.source_object || b.target_object || b.check_id || "";
      return an.localeCompare(bn);
    });

  const s = report.summary;
  const counts: Counts = {
    total: s.total,
    passed: s.passed,
    failed: s.failed,
    warning: s.warning,
    skipped: s.skipped,
    error: s.error,
    notSupported: s.not_supported,
  };
  const score = healthPct(counts);

  return { categories, issues, counts, score };
}

/** Whether a result passes the active status filter. */
export function matchesStatus(r: ValidationResult, filter: StatusFilter): boolean {
  switch (filter) {
    case "ALL":
      return true;
    case "FAILED":
      return r.status === "FAIL";
    case "WARNING":
      return r.status === "WARNING";
    case "PASSED":
      return r.status === "PASS";
    case "SKIPPED":
      return r.status === "SKIPPED";
    case "NOT_SUPPORTED":
      return r.status === "NOT_SUPPORTED";
    case "ERROR":
      return r.status === "ERROR";
  }
}

/** Free-text match over object / table / column identifiers. */
export function matchesQuery(r: ValidationResult, query: string): boolean {
  if (!query) return true;
  const haystack = `${r.source_object ?? ""} ${r.target_object ?? ""} ${r.check_id ?? ""}`.toLowerCase();
  return haystack.includes(query);
}

export function filterChecks(
  checks: ValidationResult[],
  filter: StatusFilter,
  query: string,
): ValidationResult[] {
  const q = query.trim().toLowerCase();
  return checks.filter((r) => matchesStatus(r, filter) && matchesQuery(r, q));
}
