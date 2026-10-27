import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/auth/entra.ts", import.meta.url), "utf8")
  .replace("import.meta.env.BASE_URL", '"/static/"');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const connection = {type: "azure_postgresql", host: "db.example", username: "db-role", auth_method: "entra"};

function harness(configured = true) {
  const calls = [];
  let fail = false;
  class Client {
    constructor(config) { this.config = config; calls.push(["config", config]); }
    async initialize() {}
    async acquireTokenPopup(request) { calls.push(["popup", request]); return this.result(); }
    async acquireTokenSilent(request) { calls.push(["silent", request, this.config.auth]); return this.result(); }
    result() {
      if (fail) throw new Error("provider error with sensitive details");
      return {account: {username: "signed-in@example.com"}, accessToken: "ephemeral-secret", expiresOn: new Date(Date.now() + 3600000)};
    }
  }
  const context = {exports: {}, require: () => ({PublicClientApplication: Client}),
    URL, window: {location: {origin: "http://localhost:59563"}},
    fetch: async () => ({ok: true, json: async () => ({
      client_id: configured ? "11111111-1111-1111-1111-111111111111" : "",
      tenant_id: "22222222-2222-2222-2222-222222222222",
    })}),
  };
  runInNewContext(compiled, context);
  return {auth: context.exports, calls, fail: () => { fail = true; }};
}

test("background submission authorizes once and polling never resends credentials", async () => {
  const calls = [];
  let authorizations = 0;
  let busy = false;
  const clientSource = readFileSync(new URL("../src/api/client.ts", import.meta.url), "utf8");
  const clientCode = ts.transpileModule(clientSource, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  const context = {exports: {}, URLSearchParams, require: () => ({
    authorizeMigration: async payload => {
      authorizations++;
      return {...payload, target: {...payload.target, entra_token: "memory-only"}};
    },
  }), fetch: async (url, options) => {
    calls.push({url, options});
    return {ok: !busy, status: busy ? 409 : 202, json: async () => busy
      ? {detail: "A validation is already active"}
      : {run_id: "111111111111", state: "running"}};
  }};
  runInNewContext(clientCode, context);
  const {api} = context.exports;
  await api.submitValidation({source: {}, target: {}}, "111111111111");
  await api.getRun("111111111111");
  await api.runResults("111111111111");
  assert.equal(authorizations, 1);
  assert.equal(calls[0].url, "/api/validations?run_id=111111111111");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(JSON.parse(calls[0].options.body).target.entra_token, "memory-only");
  assert.equal(calls[1].options, undefined);
  assert.equal(calls[2].options, undefined);
  assert.equal(calls.some(call => call.url.includes("memory-only")), false);
  busy = true;
  await assert.rejects(api.submitValidation({source: {}, target: {}}, "222222222222"),
    error => error.status === 409);
  assert.equal(calls.length, 4);
});

test("password auth requires no browser config and does not mutate form values", async () => {
  const {auth, calls} = harness(false);
  const original = {...connection, auth_method: "password", password: "password-secret"};
  const result = await auth.authorizeConnection(original, true);
  assert.equal(result.password, "password-secret");
  assert.notEqual(result, original);
  assert.equal(calls.length, 0);
});

test("local developer mode skips MSAL for tests and migration operations", async () => {
  const {auth, calls} = harness(false);
  const local = {...connection, entra_mode: "local", entra_token: "stale-browser-token",
    entra_token_expires_at: 9999999999, password: "not-used"};
  const result = await auth.authorizeConnection(local, true);
  assert.equal(result.entra_mode, "local");
  assert.equal(result.password, "");
  assert.equal("entra_token" in result, false);
  assert.equal("entra_token_expires_at" in result, false);
  assert.equal(local.entra_token, "stale-browser-token");
  const payload = await auth.authorizeMigration({source: local, target: local});
  assert.equal(payload.source.entra_mode, "local");
  assert.equal(payload.target.entra_mode, "local");
  assert.equal(calls.length, 0);
  assert.equal(auth.signedInAccount(local), undefined);
  await assert.rejects(auth.authorizeConnection(connection, true), /initializing/);
});

test("popup selects an account; operations renew silently with memory-only cache", async () => {
  const {auth, calls} = harness();
  await auth.initializeEntra();
  const result = await auth.authorizeConnection(connection, true);
  assert.equal(result.entra_token, "ephemeral-secret");
  assert.equal(connection.entra_token, undefined);
  assert.equal(auth.signedInAccount(connection), "signed-in@example.com");
  const config = calls.find(call => call[0] === "config")[1];
  assert.equal(config.cache.cacheLocation, "memoryStorage");
  assert.equal(config.cache.temporaryCacheLocation, "memoryStorage");
  assert.equal(config.auth.redirectUri, "http://localhost:59563/static/auth-callback.html");
  assert.equal(calls.find(call => call[0] === "popup")[1].prompt, "select_account");
  const payload = {source: {...connection, auth_method: "password"}, target: connection};
  const authorized = await auth.authorizeMigration(payload);
  assert.equal(authorized.target.entra_token, "ephemeral-secret");
  assert.equal(payload.target.entra_token, undefined);
  assert.equal(calls.filter(call => call[0] === "silent").length, 1);
  auth.forgetAccount(connection);
  await assert.rejects(auth.authorizeConnection(connection), /Test this connection again/);
});

test("missing config, unsupported engines, and cancelled sign-in fail safely", async () => {
  const missing = harness(false);
  await missing.auth.initializeEntra();
  await assert.rejects(missing.auth.authorizeConnection(connection, true), /Application \(client\) ID/);
  const {auth, fail} = harness();
  await auth.initializeEntra();
  await assert.rejects(auth.authorizeConnection({...connection, type: "azure_sql"}, true), /PostgreSQL and Azure MySQL only/);
  const mysql = await auth.authorizeConnection({...connection, type: "azure_mysql"}, true);
  assert.equal(mysql.entra_token, "ephemeral-secret");
  fail();
  await assert.rejects(auth.authorizeConnection(connection, true), error => {
    assert.match(error.message, /did not complete/);
    assert.equal(error.message.includes("sensitive"), false);
    return true;
  });
  assert.equal(auth.signedInAccount(connection), undefined);
});

test("editing connection identity requires a new explicit sign-in", async () => {
  const {auth} = harness();
  await auth.initializeEntra();
  await auth.authorizeConnection(connection, true);
  await assert.rejects(auth.authorizeConnection({...connection, host: "another.example"}), /Test this connection again/);
});

test("user registrations work without server configuration and isolate source and target", async () => {
  const {auth, calls} = harness(false);
  await auth.initializeEntra();
  const source = {...connection, entra_client_id: "33333333-3333-3333-3333-333333333333",
    entra_tenant_id: "44444444-4444-4444-4444-444444444444"};
  const target = {...source, entra_client_id: "55555555-5555-5555-5555-555555555555",
    entra_tenant_id: "66666666-6666-6666-6666-666666666666"};
  await auth.prepareEntra(source);
  await auth.authorizeConnection(source, true);
  assert.equal(auth.signedInAccount(target), undefined);
  await auth.authorizeConnection(target, true);
  const configs = calls.filter(call => call[0] === "config").map(call => call[1].auth);
  assert.equal(configs.length, 2);
  assert.equal(configs[0].clientId, source.entra_client_id);
  assert.equal(configs[1].authority, `https://login.microsoftonline.com/${target.entra_tenant_id}`);
  const result = await auth.authorizeMigration({source, target});
  assert.equal(result.source.entra_token, "ephemeral-secret");
  assert.equal(result.target.entra_token, "ephemeral-secret");
  const silentCalls = calls.filter(call => call[0] === "silent");
  assert.equal(silentCalls[0][2].clientId, source.entra_client_id);
  assert.equal(silentCalls[1][2].authority, `https://login.microsoftonline.com/${target.entra_tenant_id}`);
  for (const field of ["entra_client_id", "entra_tenant_id"]) {
    const edited = {...source, [field]: "77777777-7777-7777-7777-777777777777"};
    assert.equal(auth.signedInAccount(edited), undefined);
    await assert.rejects(auth.authorizeConnection(edited), /Test this connection again/);
  }
});

test("partial or malformed user IDs never fall back to server registration", async () => {
  const {auth, calls} = harness();
  await auth.initializeEntra();
  for (const overrides of [{entra_client_id: "bad"}, {entra_tenant_id: "22222222-2222-2222-2222-222222222222"},
    {entra_client_id: "11111111-1111-1111-1111-111111111111", entra_tenant_id: "https://untrusted.example"}]) {
    await assert.rejects(auth.authorizeConnection({...connection, ...overrides}, true), /UUIDs/);
  }
  assert.equal(calls.filter(call => call[0] === "popup").length, 0);
});