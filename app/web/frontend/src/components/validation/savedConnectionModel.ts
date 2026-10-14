import type { ConnectionInput, DatabaseType } from "../../api/types";
import type { SavedConnection } from "../../data/savedConnections";

export const connectionEngineNames: Record<DatabaseType, string> = {
  oracle: "Oracle", mysql: "MySQL", sqlserver: "SQL Server",
  azure_postgresql: "PostgreSQL", azure_sql: "Azure SQL",
};

export function matchesConnection(saved: SavedConnection, current: Partial<ConnectionInput>): boolean {
  return saved.type === current.type && saved.host.toLowerCase() === (current.host ?? "").toLowerCase() &&
    (saved.port ?? null) === (current.port ?? null) &&
    (saved.database ?? "") === (current.database ?? "") &&
    (saved.service ?? "") === (current.service ?? "") && saved.username === current.username &&
    saved.auth_method === current.auth_method && saved.ssl === current.ssl;
}

export function visibleConnections(
  saved: SavedConnection[], source: Partial<ConnectionInput>, target: Partial<ConnectionInput>,
  query: string, engine: string, expanded: boolean,
) {
  const search = query.trim().toLowerCase();
  const priority = (connection: SavedConnection) => matchesConnection(connection, source) ? 0 : matchesConnection(connection, target) ? 1 : 2;
  const matches = saved.filter(connection => (engine === "all" || engine === connection.type) &&
    [connectionEngineNames[connection.type], connection.label, connection.host, connection.database, connection.service, connection.username]
      .some(value => value?.toLowerCase().includes(search)))
    .sort((first, second) => priority(first) - priority(second));
  return { total: matches.length, items: expanded ? matches : matches.slice(0, 3) };
}