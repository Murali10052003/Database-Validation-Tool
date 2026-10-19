// Database-type field definitions — the single source of truth that keeps the
// connection form generic (mirrors the old dbTypes.js).

import type { AuthMethod, DatabaseType, DeploymentPlatform } from "../api/types";

export type FieldName =
  | "host"
  | "port"
  | "service"
  | "database"
  | "username"
  | "password"
  | "auth_method"
  | "ssl";

export interface FieldDef {
  label: string;
  type: "text" | "number" | "password" | "checkbox" | "select";
  placeholder?: string;
  options?: [string, string][];
}

export const FIELD_DEFS: Record<FieldName, FieldDef> = {
  host: { label: "Host", type: "text", placeholder: "db.example.com" },
  port: { label: "Port", type: "number" },
  service: { label: "Service name", type: "text", placeholder: "ORCLPDB1" },
  database: { label: "Database", type: "text", placeholder: "appdb" },
  username: { label: "Username", type: "text", placeholder: "user" },
  password: { label: "Password", type: "password", placeholder: "••••••••" },
  auth_method: {
    label: "Authentication",
    type: "select",
    options: [
      ["password", "Password"],
      ["entra", "Microsoft Entra ID"],
    ],
  },
  ssl: { label: "Use TLS", type: "checkbox" },
};

export interface DbTypeDef {
  value: DatabaseType;
  label: string;
  platform: DeploymentPlatform;
  fields: FieldName[];
  defaults?: Partial<Record<FieldName, string | number | boolean>> & {
    auth_method?: AuthMethod;
  };
}

export const SOURCE_DB_TYPES: DbTypeDef[] = [
  {
    value: "oracle",
    label: "Oracle",
    platform: "self_managed",
    fields: ["host", "port", "service", "username", "password", "ssl"],
    defaults: { port: 1521 },
  },
  {
    value: "mysql",
    label: "MySQL",
    platform: "self_managed",
    fields: ["host", "port", "database", "username", "password", "ssl"],
    defaults: { port: 3306 },
  },
  {
    value: "sqlserver",
    label: "SQL Server",
    platform: "self_managed",
    fields: ["host", "port", "database", "username", "auth_method", "password", "ssl"],
    defaults: { port: 1433 },
  },
  {
    value: "azure_postgresql",
    label: "Azure PostgreSQL",
    platform: "azure",
    fields: ["host", "port", "database", "username", "auth_method", "password", "ssl"],
    defaults: { port: 5432, ssl: true },
  },
  {
    value: "azure_sql",
    label: "Azure SQL",
    platform: "azure",
    fields: ["host", "port", "database", "username", "auth_method", "password", "ssl"],
    defaults: { port: 1433, ssl: true },
  },
];

export const TARGET_DB_TYPES: DbTypeDef[] = [
  {
    value: "azure_postgresql",
    label: "Azure PostgreSQL",
    platform: "azure",
    fields: ["host", "port", "database", "username", "auth_method", "password", "ssl"],
    defaults: { port: 5432, ssl: true },
  },
  {
    value: "azure_sql",
    label: "Azure SQL",
    platform: "azure",
    fields: ["host", "port", "database", "username", "auth_method", "password", "ssl"],
    defaults: { port: 1433, ssl: true },
  },
];

export function findDbType(list: DbTypeDef[], value: string): DbTypeDef {
  return list.find((d) => d.value === value) ?? list[0];
}
