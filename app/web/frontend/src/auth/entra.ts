import { PublicClientApplication, type AccountInfo } from "@azure/msal-browser";
import type { ConnectionInput, MigrationRequest } from "../api/types";

const scopes = ["https://ossrdbms-aad.database.windows.net/.default"];
const accounts = new Map<string, AccountInfo>();
const clients = new Map<string, Promise<PublicClientApplication>>();
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
let client: PublicClientApplication | undefined;
let initialization: Promise<void> | undefined;
let configurationError = "Microsoft sign-in is initializing. Try again shortly.";

function connectionKey(connection: Partial<ConnectionInput>): string {
  return JSON.stringify([connection.type, connection.host, connection.port,
    connection.database, connection.service, connection.username, connection.auth_method,
    connection.entra_mode || "browser", connection.entra_client_id?.trim().toLowerCase(),
    connection.entra_tenant_id?.trim().toLowerCase()]);
}

export function entraRedirectUri(): string {
  return new URL(`${import.meta.env.BASE_URL}auth-callback.html`, window.location.origin).href;
}

function registrationClient(clientId: string, tenantId: string): Promise<PublicClientApplication> {
  const key = JSON.stringify([clientId, tenantId]);
  let pending = clients.get(key);
  if (!pending) {
    pending = (async () => {
      const instance = new PublicClientApplication({
        auth: {
          clientId,
          authority: `https://login.microsoftonline.com/${tenantId}`,
          redirectUri: entraRedirectUri(),
        },
        cache: { cacheLocation: "memoryStorage", temporaryCacheLocation: "memoryStorage" },
      });
      await instance.initialize();
      return instance;
    })().catch(() => {
      clients.delete(key);
      throw new Error("Microsoft sign-in initialization failed. Retry Test connection.");
    });
    clients.set(key, pending);
  }
  return pending;
}

export async function prepareEntra(connection: Partial<ConnectionInput>): Promise<void> {
  if (connection.auth_method !== "entra" || connection.entra_mode === "local") return;
  const clientId = connection.entra_client_id?.trim().toLowerCase() || "";
  const tenantId = connection.entra_tenant_id?.trim().toLowerCase() || "";
  if (uuid.test(clientId) && uuid.test(tenantId)) await registrationClient(clientId, tenantId);
}

export function initializeEntra(): Promise<void> {
  initialization ??= (async () => {
    try {
      const response = await fetch("/api/auth/config");
      if (!response.ok) throw new Error("Could not load Microsoft sign-in configuration.");
      const config = await response.json();
      if (!uuid.test(config.client_id || "") || !uuid.test(config.tenant_id || "")) {
        throw new Error("Enter Application (client) ID and Directory (tenant) ID for browser sign-in.");
      }
      client = await registrationClient(config.client_id.toLowerCase(), config.tenant_id.toLowerCase());
    } catch (error) {
      configurationError = error instanceof Error ? error.message : "Microsoft sign-in initialization failed.";
    }
  })();
  return initialization;
}

export function signedInAccount(connection: Partial<ConnectionInput>): string | undefined {
  return accounts.get(connectionKey(connection))?.username;
}

export function forgetAccount(connection: Partial<ConnectionInput>): void {
  accounts.delete(connectionKey(connection));
}

export async function authorizeConnection(connection: Partial<ConnectionInput>, interactive = false): Promise<Partial<ConnectionInput>> {
  if (connection.auth_method !== "entra") return { ...connection };
  if (connection.type !== "azure_postgresql") {
    throw new Error("Browser Microsoft sign-in is currently supported for Azure PostgreSQL only.");
  }
  if (connection.entra_mode === "local") {
    const { entra_token, entra_token_expires_at, ...metadata } = connection;
    return { ...metadata, password: "" };
  }
  const clientId = connection.entra_client_id?.trim().toLowerCase() || "";
  const tenantId = connection.entra_tenant_id?.trim().toLowerCase() || "";
  let selectedClient = client;
  if (clientId || tenantId) {
    if (!uuid.test(clientId) || !uuid.test(tenantId)) {
      throw new Error("Enter valid Application (client) ID and Directory (tenant) ID values (UUIDs).");
    }
    selectedClient = await registrationClient(clientId, tenantId);
  }
  if (!selectedClient) throw new Error(configurationError);
  const key = connectionKey(connection);
  const account = accounts.get(key);
  try {
    const result = interactive
      ? await selectedClient.acquireTokenPopup({ scopes, prompt: "select_account", loginHint: connection.username })
      : account
        ? await selectedClient.acquireTokenSilent({ scopes, account })
        : undefined;
    if (!result?.account || !result.accessToken || !result.expiresOn) {
      throw new Error("Sign-in required");
    }
    if (result.expiresOn.getTime() <= Date.now() + 60000) throw new Error("Token expired");
    accounts.set(key, result.account);
    return { ...connection, password: "", entra_token: result.accessToken,
      entra_token_expires_at: Math.floor(result.expiresOn.getTime() / 1000) };
  } catch {
    accounts.delete(key);
    throw new Error(interactive
      ? "Microsoft sign-in did not complete. Retry Test connection and check popup permissions, tenant consent, and account access."
      : "Microsoft sign-in is required or has expired. Test this connection again.");
  }
}

export async function authorizeMigration(payload: MigrationRequest): Promise<MigrationRequest> {
  const source = await authorizeConnection(payload.source);
  const target = await authorizeConnection(payload.target);
  return { ...payload, source, target };
}