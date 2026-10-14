import type { PlanResponse } from "../../api/types";

// A matched / unmatched view of the tables a plan covers, grouped by source schema, plus the
// helpers the object-scope review needs. Pure functions only so they can be unit tested.

export type RowState = "matched" | "mapped" | "review" | "source-only";
export type StatusFilter = "all" | "attention" | "matched" | "review" | "source-only" | "excluded";

export interface ReviewRow {
  // SCHEMA.TABLE: the key used by included/excluded objects and by table overrides.
  id: string;
  schema: string;
  table: string;
  // Qualified target (schema.table), or "" when there is none.
  target: string;
  state: RowState;
  // A likely target among the unmapped target tables (unqualified name).
  suggestion?: { target: string; score: number };
}

export interface ReviewGroup {
  schema: string;
  targetSchema: string;
  rows: ReviewRow[];
  // Target tables of the matched schema that no source table maps to (unqualified).
  unmapped: string[];
}

export interface ScopeState {
  all: boolean;
  included: string[];
  excluded: string[];
}

export interface ReviewCounts {
  total: number;
  matched: number;
  review: number;
  sourceOnly: number;
  targetOnly: number;
  included: number;
  excluded: number;
}

export const MIN_SUGGESTION = 0.8;
const MAX_SUGGESTION_PAIRS = 40_000;
const lower = (value: string) => value.toLowerCase();

function levenshtein(a: string, b: string): number {
  let previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    for (let j = 1; j <= b.length; j++) {
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    previous = current;
  }
  return previous[b.length];
}

// 0..1 similarity ignoring case and punctuation (CUSTOMER_ITEMS vs customer_item).
export function similarity(a: string, b: string): number {
  const normalise = (value: string) => lower(value).replace(/[^a-z0-9]/g, "");
  const x = normalise(a), y = normalise(b);
  if (!x || !y) return 0;
  return x === y ? 1 : 1 - levenshtein(x, y) / Math.max(x.length, y.length);
}

// One-to-one best matches between unmatched source tables and unmapped target tables.
export function suggestTargets(tables: string[], targets: string[]): Map<string, { target: string; score: number }> {
  const result = new Map<string, { target: string; score: number }>();
  if (!tables.length || !targets.length || tables.length * targets.length > MAX_SUGGESTION_PAIRS) return result;
  const pairs: { table: string; target: string; score: number }[] = [];
  for (const table of tables) {
    for (const target of targets) {
      const score = similarity(table, target);
      if (score >= MIN_SUGGESTION) pairs.push({ table, target, score });
    }
  }
  pairs.sort((a, b) => b.score - a.score || a.table.localeCompare(b.table));
  const usedTargets = new Set<string>();
  for (const pair of pairs) {
    if (result.has(pair.table) || usedTargets.has(pair.target)) continue;
    result.set(pair.table, { target: pair.target, score: pair.score });
    usedTargets.add(pair.target);
  }
  return result;
}

export function buildReview(plan: PlanResponse, schemas: Record<string, string>, overrides: Record<string, string>): ReviewGroup[] {
  const mapped = new Map(Object.entries(overrides).map(([key, value]) => [lower(key), value.trim()] as [string, string]).filter(([, value]) => value));
  return plan.schema_matches.map(match => {
    const targetSchema = schemas[match.source] || match.target;
    const freed: string[] = [];
    const row = (table: string, auto: string): ReviewRow => {
      const id = `${match.source}.${table}`;
      const override = mapped.get(lower(id));
      if (override && lower(override) !== lower(auto)) {
        if (auto) freed.push(auto.slice(auto.indexOf(".") + 1));
        return { id, schema: match.source, table, target: override, state: "mapped" };
      }
      return { id, schema: match.source, table, target: auto, state: auto ? "matched" : "source-only" };
    };
    const rows = [
      ...match.matched_tables.map(table => row(table.source, `${targetSchema}.${table.target}`)),
      ...match.unmatched_source_tables.map(table => row(table, "")),
    ].sort((a, b) => a.table.localeCompare(b.table));
    const prefix = `${lower(targetSchema)}.`;
    const used = new Set(rows.filter(item => lower(item.target).startsWith(prefix)).map(item => lower(item.target.slice(prefix.length))));
    const unmapped = [...new Set([...match.unmatched_target_tables, ...freed])]
      .filter(table => !used.has(lower(table)))
      .sort((a, b) => a.localeCompare(b));
    const suggestions = suggestTargets(rows.filter(item => item.state === "source-only").map(item => item.table), unmapped);
    for (const item of rows) {
      const suggestion = item.state === "source-only" ? suggestions.get(item.table) : undefined;
      if (suggestion) Object.assign(item, { state: "review" as const, suggestion });
    }
    return { schema: match.source, targetSchema, rows, unmapped };
  });
}

// Unmapped target tables that are not simply the suggestion for some source table.
export function targetOnlyTables(group: ReviewGroup): string[] {
  const suggested = new Set(group.rows.map(row => lower(row.suggestion?.target ?? "")));
  return group.unmapped.filter(table => !suggested.has(lower(table)));
}

/* ------------------------------------------------------------------ object scope */

// Excluded objects always win; an object matches a name equal to it or to one of its parents (schema).
export function scopeMatcher(scope: ScopeState): (id: string) => boolean {
  const hit = (names: Set<string>, id: string) => {
    const key = lower(id);
    if (names.has(key)) return true;
    for (let dot = key.indexOf("."); dot > 0; dot = key.indexOf(".", dot + 1)) if (names.has(key.slice(0, dot))) return true;
    return false;
  };
  const included = new Set(scope.included.map(lower)), excluded = new Set(scope.excluded.map(lower));
  return id => (scope.all || hit(included, id)) && !hit(excluded, id);
}

export function setInclusion(scope: ScopeState, ids: string[], checked: boolean): ScopeState {
  const keys = new Set(ids.map(lower));
  if (checked) {
    const excluded = scope.excluded.filter(name => !keys.has(lower(name)));
    if (scope.all) return { ...scope, excluded };
    const covered = scopeMatcher({ ...scope, excluded });
    return { ...scope, excluded, included: [...scope.included, ...ids.filter(id => !covered(id))] };
  }
  const included = scope.included.filter(name => !keys.has(lower(name)));
  const still = scopeMatcher({ ...scope, included });
  return { ...scope, included, excluded: [...scope.excluded, ...ids.filter(still)] };
}

export function reviewCounts(groups: ReviewGroup[], scope: ScopeState): ReviewCounts {
  const included = scopeMatcher(scope);
  const counts: ReviewCounts = { total: 0, matched: 0, review: 0, sourceOnly: 0, targetOnly: 0, included: 0, excluded: 0 };
  for (const group of groups) {
    counts.targetOnly += targetOnlyTables(group).length;
    for (const row of group.rows) {
      counts.total++;
      if (row.state === "review") counts.review++;
      else if (row.state === "source-only") counts.sourceOnly++;
      else counts.matched++;
      included(row.id) ? counts.included++ : counts.excluded++;
    }
  }
  return counts;
}

export function rowVisible(row: ReviewRow, included: boolean, filter: StatusFilter, query: string): boolean {
  const needle = lower(query.trim());
  if (needle && !lower(`${row.table} ${row.target} ${row.suggestion?.target ?? ""}`).includes(needle)) return false;
  switch (filter) {
    case "attention": return row.state === "review" || row.state === "source-only";
    case "matched": return row.state === "matched" || row.state === "mapped";
    case "review":
    case "source-only": return row.state === filter;
    case "excluded": return !included;
    default: return true;
  }
}

/* ------------------------------------------------------------------ CSV */

const csvField = (value: string) => (/[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);

export function toCsv(groups: ReviewGroup[], scope: ScopeState): string {
  const included = scopeMatcher(scope);
  const lines = [["schema", "source_table", "target_table", "suggested_target", "status", "included"].join(",")];
  for (const group of groups) {
    for (const row of group.rows) {
      lines.push([row.schema, row.table, row.target, row.suggestion ? `${group.targetSchema}.${row.suggestion.target}` : "", row.state, String(included(row.id))].map(csvField).join(","));
    }
  }
  return lines.join("\n");
}

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") { row.push(field); field = ""; }
    else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.some(value => value.trim())) rows.push(row);
      row = [];
    } else field += char;
  }
  row.push(field);
  if (row.some(value => value.trim())) rows.push(row);
  return rows;
}

export function withOverride(overrides: Record<string, string>, id: string, target: string | null): Record<string, string> {
  const next = Object.fromEntries(Object.entries(overrides).filter(([key]) => lower(key) !== lower(id)));
  if (target) next[id] = target;
  return next;
}

export interface ImportResult {
  overrides: Record<string, string>;
  scope: ScopeState;
  applied: number;
  rejected: string[];
}

// Apply an edited export: target_table remaps a table to an unmapped target; included toggles scope.
export function applyImport(groups: ReviewGroup[], scope: ScopeState, overrides: Record<string, string>, text: string): ImportResult {
  const rows = parseCsv(text);
  const header = (rows[0] ?? []).map(name => lower(name.trim()));
  const column = (name: string) => header.indexOf(name);
  const [schemaAt, tableAt, targetAt, includedAt] = [column("schema"), column("source_table"), column("target_table"), column("included")];
  if (schemaAt < 0 || tableAt < 0) throw new Error("The CSV needs schema and source_table columns.");
  const known = new Map(groups.flatMap(group => group.rows.map(row => [lower(row.id), { row, group }] as const)));
  const pool = new Map(groups.flatMap(group => group.unmapped.map(table => [lower(`${group.targetSchema}.${table}`), `${group.targetSchema}.${table}`] as const)));
  let next = overrides;
  const include: string[] = [], exclude: string[] = [], rejected: string[] = [];
  let applied = 0;
  for (const cells of rows.slice(1)) {
    const id = `${(cells[schemaAt] ?? "").trim()}.${(cells[tableAt] ?? "").trim()}`;
    const entry = known.get(lower(id));
    if (!entry) { rejected.push(`${id}: not part of this plan`); continue; }
    let changed = false;
    const raw = targetAt < 0 ? undefined : (cells[targetAt] ?? "").trim();
    if (raw === "") {
      if (entry.row.state === "mapped") { next = withOverride(next, entry.row.id, null); changed = true; }
    } else if (raw !== undefined) {
      const qualified = raw.includes(".") ? raw : `${entry.group.targetSchema}.${raw}`;
      if (lower(qualified) !== lower(entry.row.target)) {
        const hit = pool.get(lower(qualified));
        if (!hit) { rejected.push(`${id}: ${raw} is not an unmapped target table`); continue; }
        pool.delete(lower(qualified));
        next = withOverride(next, entry.row.id, hit);
        changed = true;
      }
    }
    const flag = includedAt < 0 ? "" : lower((cells[includedAt] ?? "").trim());
    if (["true", "yes", "1"].includes(flag)) { include.push(entry.row.id); changed = true; }
    if (["false", "no", "0"].includes(flag)) { exclude.push(entry.row.id); changed = true; }
    if (changed) applied++;
  }
  return { overrides: next, scope: setInclusion(setInclusion(scope, include, true), exclude, false), applied, rejected };
}
