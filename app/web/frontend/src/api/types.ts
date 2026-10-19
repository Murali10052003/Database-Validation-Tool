// Types mirroring the FastAPI schemas in app/schemas/api.py and app/reporting.

export type DatabaseType =
  | "oracle"
  | "mysql"
  | "sqlserver"
  | "azure_postgresql"
  | "azure_sql";

export type DeploymentPlatform = "self_managed" | "azure" | "unknown";
export type AuthMethod = "password" | "entra";
export type ValidationProfileName = "quick" | "standard" | "full" | "custom";
export type ValidationCheck = "schema" | "constraints" | "indexes" | "sequences" | "views" | "routines" | "triggers" | "partitions" | "rules" | "row_count" | "null_count" | "aggregate" | "referential_integrity" | "checksum";

export type ValidationStatus =
  | "PASS"
  | "FAIL"
  | "WARNING"
  | "SKIPPED"
  | "NOT_SUPPORTED"
  | "ERROR";

export interface ConnectionInput {
  type: DatabaseType;
  platform: DeploymentPlatform;
  host: string;
  port: number | null;
  service?: string | null;
  database?: string | null;
  username: string;
  password: string;
  entra_token?: string;
  entra_token_expires_at?: number;
  auth_method: AuthMethod;
  entra_mode?: "browser" | "local";
  entra_client_id?: string;
  entra_tenant_id?: string;
  ssl: boolean;
}

export interface MappingInput {
  type_overrides?: Record<string, string>;
  schemas: Record<string, string>;
  tables: Record<string, string>;
  columns?: Record<string, string>;
  included_objects?: string[];
  excluded_objects: string[];
}

export interface MigrationRequest {
  discovery_mode?: "full" | "refresh" | "reuse";
  source_inventory_id?: string | null;
  target_inventory_id?: string | null;
  mapping_version_id?: string | null;
  selected_checks?: ValidationCheck[];
  name?: string;
  source: Partial<ConnectionInput>;
  target: Partial<ConnectionInput>;
  mapping?: Partial<MappingInput>;
  profile: ValidationProfileName;
  // Independent per-side discovery scope; omit to keep legacy all-schema behaviour.
  source_schemas?: string[];
  target_schemas?: string[];
}

export interface SchemaListResponse {
  database_type: DatabaseType;
  version?: string | null;
  schemas: string[];
}

export interface ConnectionCheck {
  success: boolean;
  database_type: DatabaseType;
  version?: string | null;
  latency_ms?: number | null;
  message?: string | null;
  error?: string | null;
}

export interface TestConnectionResponse {
  source: ConnectionCheck;
  target: ConnectionCheck;
}

export interface ObjectCounts {
  database_type: DatabaseType;
  version?: string | null;
  schemas: number;
  tables: number;
  columns: number;
  indexes: number;
  constraints: number;
  sequences: number;
  views: number;
}

export interface TableMatch {
  source: string;
  target: string;
  match_type: string;
}

export interface SchemaMatch {
  source: string;
  target: string;
  match_type: string;
  matched_tables: TableMatch[];
  unmatched_source_tables: string[];
  unmatched_target_tables: string[];
}

export interface AmbiguousMatch {
  source: string;
  candidates: string[];
}

export interface PlanProgress {
  state: "running" | "completed" | "failed";
  percent?: number;
  stage?: string;
  message?: string;
  error?: string;
}

export interface PlanResponse {
  source_inventory_id?: string | null;
  target_inventory_id?: string | null;
  mapping_version_id?: string | null;
  saved_mapping?: MappingInput | null;
  source: ObjectCounts;
  target: ObjectCounts;
  schema_matches: SchemaMatch[];
  unmatched_source_schemas: string[];
  unmatched_target_schemas: string[];
  ambiguous_schemas: AmbiguousMatch[];
  suggested_mapping: Record<string, string>;
  // false = inventories hold schema/table names only; other metadata is collected at validation time.
  metadata_complete?: boolean;
  source_scope?: string[] | null;
  target_scope?: string[] | null;
}

export interface ValidationSummary {
  total: number;
  passed: number;
  failed: number;
  warning: number;
  skipped: number;
  not_supported: number;
  error: number;
}

export interface ValidationResult {
  coverage?: Record<string, unknown> | null;
  classification?: "datatype" | "column_attributes" | "execution" | null;
  validation_scope?: string | null;
  duration_scope?: string | null;
  check_id: string;
  category: string;
  object_type?: string | null;
  source_object?: string | null;
  target_object?: string | null;
  status: ValidationStatus;
  severity: string;
  source_value?: unknown;
  target_value?: unknown;
  differences: string[];
  duration_ms?: number | null;
  error?: string | null;
  message?: string | null;
}

export interface ValidationReport {
  run_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  coverage?: {
    discovery_mode?: string;
    source_inventory_id?: string | null;
    target_inventory_id?: string | null;
    mapping_version_id?: string | null;
    metadata_warning?: string | null;
    selected_stages: string[];
    not_selected_stages: string[];
    not_reached_stages: string[];
    reached_stages: string[];
    included_objects?: string[];
    excluded_objects: string[];
    schema_options: Record<string, boolean>;
    sample_limit?: number | null;
    checksum_limit: number;
    snapshot_consistent: boolean;
  } | null;
  migration_id: string;
  migration_name: string;
  generated_at: string;
  profile: string;
  summary: ValidationSummary;
  overall_status: ValidationStatus;
  duration_ms?: number | null;
  results: ValidationResult[];
}

export interface ReportListItem {
  migration_id: string;
  migration_name: string;
  generated_at: string;
  profile: string;
  overall_status: ValidationStatus;
  total: number;
  passed: number;
  failed: number;
  warning: number;
  duration_ms?: number | null;
}

export interface PartialRunReport {
  run_id: string;
  state: string;
  error: string | null;
  coverage_complete: boolean;
  stages: { stage: string; status: string; updated_at: string }[];
  counts: Record<string, number>;
  total: number;
  offset: number;
  limit: number;
  results: ValidationResult[];
}

export interface RunRecord {
  id: string;
  name: string;
  profile: string;
  started_at: string;
  finished_at: string | null;
  state: string;
  outcome: string | null;
  report_id: string | null;
}

export interface RunEvent {
  id: number;
  run_id: string;
  time: string;
  level: string;
  stage: string;
  event: string;
  details: Record<string, unknown>;
}
