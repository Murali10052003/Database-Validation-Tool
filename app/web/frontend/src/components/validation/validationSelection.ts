export function schemaMapping(plan: PlanResponse, saved?: Record<string, string>): Record<string, string> {
  const stored = new Map(Object.entries(saved || {}).map(([source, target]) => [source.toLowerCase(), target]));
  const entries: [string, string][] = [
    ...plan.schema_matches.map(match => [match.source, stored.get(match.source.toLowerCase()) ?? match.target] as [string, string]),
    ...plan.unmatched_source_schemas.map(source => [source, stored.get(source.toLowerCase()) ?? ""] as [string, string]),
    ...plan.ambiguous_schemas.map(match => [match.source, stored.get(match.source.toLowerCase()) ?? ""] as [string, string]),
  ];
  return Object.fromEntries(entries.map(([source, target]) => [source, target.trim()]));
}

export function schemaMatchType(source: string, target: string, targets: string[]): string {
  const name = target.trim();
  if (!name) return "unmatched";
  const candidates = targets.filter(candidate => candidate.toLowerCase() === name.toLowerCase());
  const resolved = targets.includes(name) ? name : candidates.length === 1 ? candidates[0] : undefined;
  if (!resolved) return candidates.length > 1 ? "ambiguous" : "unmatched";
  return source === resolved ? "exact" : source.toLowerCase() === resolved.toLowerCase() ? "case_insensitive" : "explicit";
}
import type { DatabaseType, PlanResponse, ValidationCheck, ValidationProfileName } from "../../api/types";

export const VALIDATION_CHECKS: { id: ValidationCheck; label: string }[] = [
  { id: "schema", label: "Schema" },
  { id: "constraints", label: "Constraints" },
  { id: "indexes", label: "Indexes" },
  { id: "sequences", label: "Sequences" },
  { id: "views", label: "Views" },
  { id: "routines", label: "Routines" },
  { id: "triggers", label: "Triggers" },
  { id: "partitions", label: "Partitions" },
  { id: "rules", label: "Compatibility rules" },
  { id: "row_count", label: "Row counts" },
  { id: "null_count", label: "Null counts" },
  { id: "aggregate", label: "Aggregates" },
  { id: "referential_integrity", label: "Referential integrity" },
  { id: "checksum", label: "Checksums" },
];

export function presetChecks(profile: ValidationProfileName): ValidationCheck[] {
  if (profile === "quick") return ["schema", "row_count"];
  return VALIDATION_CHECKS.slice(0, profile === "full" ? undefined : 11).map(check => check.id);
}

export function parseObjects(value: string): string[] {
  return [...new Set(value.split(",").map(name => name.trim()).filter(Boolean))];
}

export function objectInScope(source: string, selection: string[]): boolean {
  return selection.some(name => source.toLowerCase() === name.toLowerCase() || source.toLowerCase().startsWith(`${name.toLowerCase()}.`));
}

export function scopeRows(plan: PlanResponse) {
  return plan.schema_matches.flatMap(match => [
    ...match.matched_tables.map(table => ({ source: `${match.source}.${table.source}`, schema: match.source, target: table.target, targetSchema: match.target })),
    ...match.unmatched_source_tables.map(table => ({ source: `${match.source}.${table}`, schema: match.source, target: "", targetSchema: match.target })),
  ]);
}

// Both sides must have an explicit schema selection before Discover & match runs.
export function scopeReady(source: string[], target: string[]): boolean {
  return source.length > 0 && target.length > 0;
}

// Schemas a loaded plan covers; falls back to the plan's matches for older responses.
export function planScope(plan: PlanResponse): { source: string[]; target: string[] } {
  const matched = plan.schema_matches.filter(match => match.match_type !== "unmatched" && match.target).map(match => match.target);
  return {
    source: plan.source_scope ?? plan.schema_matches.map(match => match.source),
    target: plan.target_scope ?? [...new Set([...matched, ...plan.unmatched_target_schemas])],
  };
}

// Inventories without full metadata cannot be refreshed or reused: validation must collect
// the required metadata live, but only inside the saved schema scope.
export function metadataMode(plan: PlanResponse): "refresh" | "full" {
  return plan.metadata_complete === false ? "full" : "refresh";
}

export function scopeSelection(selected: string[], available: string[] | null): string[] {
  return [...new Set([...(available ?? []), ...selected])];
}

export function toggleSchema(selected: string[], name: string): string[] {
  return selected.includes(name) ? selected.filter(item => item !== name) : [...selected, name];
}

const SQL_SERVER_SYSTEM = ["sys", "INFORMATION_SCHEMA", "guest", "db_owner", "db_accessadmin", "db_securityadmin", "db_ddladmin", "db_backupoperator", "db_datareader", "db_datawriter", "db_denydatareader", "db_denydatawriter"];
const SYSTEM_SCHEMAS: Record<DatabaseType, { names: string[]; patterns: RegExp[] }> = {
  oracle: {
    names: ["ANONYMOUS", "APPQOSSYS", "AUDSYS", "BAASSYS", "CTXSYS", "DBSFWUSER", "DBSNMP", "DGPDB_INT", "DIP", "DVF", "DVSYS", "EXFSYS", "GGSHAREDCAP", "GGSYS", "GSMADMIN_INTERNAL", "GSMCATUSER", "GSMUSER", "LBACSYS", "MDDATA", "MDSYS", "OJVMSYS", "OLAPSYS", "ORACLE_OCM", "ORDDATA", "ORDPLUGINS", "ORDSYS", "OUTLN", "PDBADMIN", "REMOTE_SCHEDULER_AGENT", "SI_INFORMTN_SCHEMA", "SPATIAL_CSW_ADMIN_USR", "SPATIAL_WFS_ADMIN_USR", "SYS", "SYS$UMF", "SYSBACKUP", "SYSDG", "SYSKM", "SYSRAC", "SYSTEM", "VECSYS", "WMSYS", "XDB", "XS$NULL"],
    patterns: [/^APEX_/i, /^FLOWS_/i],
  },
  azure_postgresql: { names: ["information_schema", "azure_pg_admin", "azure_sys"], patterns: [/^pg_/i] },
  mysql: { names: ["mysql", "information_schema", "performance_schema", "sys"], patterns: [] },
  sqlserver: { names: SQL_SERVER_SYSTEM, patterns: [] },
  azure_sql: { names: SQL_SERVER_SYSTEM, patterns: [] },
};

// Engine-owned schemas that are rarely migrated; hidden from the picker unless asked for.
export function isSystemSchema(name: string, engine?: DatabaseType): boolean {
  const known = engine ? SYSTEM_SCHEMAS[engine] : undefined;
  if (!known) return false;
  const key = name.toLowerCase();
  return known.names.some(item => item.toLowerCase() === key) || known.patterns.some(pattern => pattern.test(name));
}

export interface SchemaFilter {
  query: string;
  showSystem: boolean;
  engine?: DatabaseType;
}

export function filterSchemas(names: string[], { query, showSystem, engine }: SchemaFilter): string[] {
  const needle = query.trim().toLowerCase();
  return names.filter(name => (showSystem || !isSystemSchema(name, engine)) && (!needle || name.toLowerCase().includes(needle)));
}

// Whitespace/comma separated names, where * and ? are wildcards, matched case-insensitively.
export function globMatcher(text: string): ((name: string) => boolean) | null {
  const patterns = text.split(/[\s,]+/).filter(Boolean).map(token =>
    new RegExp(`^${token.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".")}$`, "i"));
  return patterns.length ? name => patterns.some(pattern => pattern.test(name)) : null;
}

export function matchSchemas(names: string[], text: string): string[] {
  const matches = globMatcher(text);
  return matches ? names.filter(matches) : [];
}

export function addSchemas(selected: string[], names: string[]): string[] {
  return [...new Set([...selected, ...names])];
}

export function invertSchemas(selected: string[], names: string[]): string[] {
  const visible = new Set(names);
  return [...selected.filter(name => !visible.has(name)), ...names.filter(name => !selected.includes(name))];
}

// Target schemas whose names match the chosen source schemas (ignoring case) but are not selected yet.
export function suggestTargetSchemas(source: string[], available: string[] | null, selected: string[]): string[] {
  const byKey = new Map((available ?? []).map(name => [name.toLowerCase(), name]));
  return [...new Set(source.map(name => byKey.get(name.toLowerCase())).filter((name): name is string => !!name && !selected.includes(name)))];
}