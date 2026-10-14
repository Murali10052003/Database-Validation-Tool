// Backend-persisted connection metadata. Browser storage is read only for import.

import { useEffect, useSyncExternalStore } from "react";
import type { AuthMethod, DatabaseType, DeploymentPlatform } from "../api/types";

export interface SavedConnection {
  id: string;
  label: string;
  type: DatabaseType;
  platform: DeploymentPlatform;
  host: string;
  port: number | null;
  service?: string | null;
  database?: string | null;
  username: string;
  auth_method: AuthMethod;
  ssl: boolean;
}

const STORAGE_KEY = "mv.savedConnections";
const listeners = new Set<() => void>();
let cache: SavedConnection[] = [];
let error = "";

export function legacyConnections(): SavedConnection[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function publish(next: SavedConnection[]): void {
  cache = next;
  listeners.forEach((l) => l());
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`Connection catalog request failed (${response.status})`);
  return response.json();
}

export async function refreshConnections(): Promise<void> {
  try { const values = await request<SavedConnection[]>("/api/connections"); error = ""; publish(values); }
  catch (reason) { error = String(reason); publish([...cache]); }
}

export function connectionStorageError(): string { return error; }

export async function importLegacyConnections(): Promise<void> {
  for (const entry of legacyConnections()) {
    await saveConnection(entry);
  }
}

// Identity of a connection ignores the secret so re-saving updates in place.
function keyOf(c: Pick<SavedConnection, "type" | "host" | "database" | "service" | "username">): string {
  return [c.type, c.host, c.database ?? c.service ?? "", c.username].join("|").toLowerCase();
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export async function saveConnection(entry: Omit<SavedConnection, "id"> & { id?: string }): Promise<SavedConnection> {
  const existing = cache.find((c) => entry.id ? c.id === entry.id : keyOf(c) === keyOf(entry));
  const { label, type, platform, host, port, service, database, username, auth_method, ssl } = entry;
  const saved = await request<SavedConnection>("/api/connections", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: existing?.id || entry.id || newId(), label, type, platform, host, port, service, database, username, auth_method, ssl }),
  });
  publish([saved, ...cache.filter(connection => connection.id !== saved.id)]);
  return saved;
}

export async function deleteConnection(id: string): Promise<void> {
  await request(`/api/connections/${encodeURIComponent(id)}`, { method: "DELETE" });
  publish(cache.filter((c) => c.id !== id));
}

export function useSavedConnections(): SavedConnection[] {
  useEffect(() => { void refreshConnections(); }, []);
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => cache,
    () => cache,
  );
}
