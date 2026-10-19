import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/validation/savedConnectionModel.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const profiles = Array.from({ length: 10 }, (_, index) => ({
  id: String(index), label: `user@host${index}`, type: "azure_postgresql", host: `host${index}`,
  port: 5432, database: "finance", service: null, username: "user", auth_method: "password", ssl: true,
}));

test("three cards initially, selected roles first, and all ten on expansion", () => {
  const result = model.visibleConnections(profiles, profiles[8], profiles[9], "", "all", false);
  assert.deepEqual(result.items.map(profile => profile.id), ["8", "9", "0"]);
  assert.equal(result.total, 10);
  assert.equal(model.visibleConnections(profiles, {}, {}, "", "all", true).items.length, 10);
  assert.equal(profiles[0].id, "0");
});

test("search covers hidden profiles and engine filters apply before limiting", () => {
  assert.equal(model.visibleConnections(profiles, {}, {}, "host9", "all", false).items[0].id, "9");
  assert.equal(model.visibleConnections(profiles, {}, {}, "", "oracle", false).total, 0);
  assert.equal(model.visibleConnections(profiles, {}, {}, "not-found", "all", false).total, 0);
});

test("selection ignores secrets but detects edits to connection settings", () => {
  assert.equal(model.matchesConnection(profiles[0], { ...profiles[0], password: "not-stored" }), true);
  for (const change of [{ port: 5433 }, { database: "other" }, { auth_method: "entra" }, { ssl: false }, { username: "other" }]) {
    assert.equal(model.matchesConnection(profiles[0], { ...profiles[0], ...change }), false);
  }
  assert.equal(model.connectionEngineNames.azure_postgresql, "PostgreSQL");
});

test("backend profile storage strips secrets, retains browser originals and surfaces failures", async () => {
  const storageSource = readFileSync(new URL("../src/data/savedConnections.ts", import.meta.url), "utf8");
  const javascript = ts.transpileModule(storageSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const legacy = JSON.stringify([{ ...profiles[0], password: "never-store", token: "never-store" }]);
  const requests = [];
  let fail = false;
  const context = { exports: {}, require: () => ({}), localStorage: {getItem: () => legacy},
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: !fail, status: fail ? 503 : 200, json: async () => options?.body ? JSON.parse(options.body) : []};
    },
  };
  runInNewContext(javascript, context);
  await context.exports.importLegacyConnections();
  const payload = JSON.parse(requests[0].options.body);
  assert.equal(payload.id, profiles[0].id);
  assert.equal("password" in payload, false);
  assert.equal("token" in payload, false);
  assert.equal(context.exports.legacyConnections().length, 1);
  await context.exports.importLegacyConnections();
  assert.equal(JSON.parse(requests[1].options.body).id, payload.id);
  fail = true;
  await assert.rejects(context.exports.saveConnection(profiles[0]), /503/);
  await context.exports.refreshConnections();
  assert.match(context.exports.connectionStorageError(), /503/);
});