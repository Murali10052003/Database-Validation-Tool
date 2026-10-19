// Thin, typed client over the FastAPI /api endpoints.

import type {
  ConnectionCheck,
  ConnectionInput,
  MigrationRequest,
  PlanProgress,
  PlanResponse,
  ReportListItem,
  SchemaListResponse,
  TestConnectionResponse,
  ValidationReport,
  RunRecord,
  RunEvent,
  PartialRunReport,
} from "./types";
import { authorizeMigration } from "../auth/entra";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      (typeof data?.detail === "string" ? data.detail :
        Array.isArray(data?.detail) ? data.detail.map((error: {msg?: string}) => error.msg || "Invalid request").join("; ") : "") || `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  return data as T;
}

function postJSON<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  inventorySearch: (payload: MigrationRequest) => postJSON<{
    source: {id: string; created_at: string; metadata_complete?: boolean}[];
    target: {id: string; created_at: string; metadata_complete?: boolean}[];
    mappings: {id: string; source_inventory: string; target_inventory: string; created_at: string; payload: NonNullable<MigrationRequest["mapping"]>}[];
    runs: {id: string; created_at: string; status: string; configuration: {mapping: NonNullable<MigrationRequest["mapping"]>; validation: {profile: MigrationRequest["profile"]; selected_checks: MigrationRequest["selected_checks"]}; source_inventory_id?: string; target_inventory_id?: string}; report: ValidationReport | null}[];
  }>("/api/inventories/search", payload),
  inventoryPlan: (payload: MigrationRequest) => postJSON<PlanResponse>("/api/inventories/plan", payload),
  saveMapping: (payload: MigrationRequest) => postJSON<{id: string}>("/api/mappings", payload),
  backupCatalog: () => postJSON<{filename: string}>("/api/catalog/backup", {}),
  health: () => request<{ status: string }>("/api/health"),
  supported: () => request<{ database_types: string[] }>("/api/supported"),
  testConnection: (payload: MigrationRequest) =>
    postJSON<TestConnectionResponse>("/api/test-connection", payload),
  testSingleConnection: (payload: Partial<ConnectionInput>) =>
    postJSON<ConnectionCheck>("/api/test-connection/single", payload),
  listSchemas: (payload: Partial<ConnectionInput>) =>
    postJSON<SchemaListResponse>("/api/schemas", payload),
  plan: async (payload: MigrationRequest, progressId?: string) =>
    postJSON<PlanResponse>(`/api/plan${progressId ? `?progress_id=${encodeURIComponent(progressId)}` : ""}`, await authorizeMigration(payload)),
  planProgress: (progressId: string) => request<PlanProgress>(`/api/plan/progress/${encodeURIComponent(progressId)}`),
  validate: async (payload: MigrationRequest, runId?: string) =>
    postJSON<ValidationReport>(`/api/validate${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`, await authorizeMigration(payload)),
  submitValidation: async (payload: MigrationRequest, runId: string) =>
    postJSON<{ run_id: string; status_url: string }>(`/api/validations?run_id=${encodeURIComponent(runId)}`, await authorizeMigration(payload)),
  listRuns: (offset = 0) => request<RunRecord[]>(`/api/runs?limit=100&offset=${offset}`),
  getRun: (id: string) => request<RunRecord>(`/api/runs/${encodeURIComponent(id)}`),
  runResults: (id: string, offset = 0) =>
    request<PartialRunReport>(`/api/runs/${encodeURIComponent(id)}/results?limit=100&offset=${offset}`),
  runEvents: (id: string, options: Record<string, string> = {}) =>
    request<{ total: number; items: RunEvent[] }>(`/api/runs/${encodeURIComponent(id)}/events?${new URLSearchParams(options)}`),
  runLogUrl: (id: string) => `/api/runs/${encodeURIComponent(id)}/download`,
  listReports: () => request<ReportListItem[]>("/api/reports"),
  getReport: (id: string) => request<ValidationReport>(`/api/reports/${id}`),
  reportUrl: (id: string, format: "html" | "csv") => `/api/reports/${id}.${format}`,
};
