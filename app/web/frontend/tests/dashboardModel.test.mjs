import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/pages/dashboardModel.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const summary = { total: 100, passed: 100, failed: 0, warning: 0, error: 0, skipped: 0, not_supported: 0 };

test("dashboard prioritizes errors and failures over passed checks", () => {
  assert.equal(model.dashboardStatus({ overall_status: "PASS", summary: { ...summary, passed: 99, failed: 1 } }), "FAIL");
  assert.equal(model.dashboardStatus({ overall_status: "FAIL", summary: { ...summary, error: 1, failed: 1 } }), "ERROR");
  assert.equal(model.dashboardStatus({ overall_status: "PASS", summary }), "PASS");
});

test("empty, skipped, unsupported and unreached checks cannot appear passed", () => {
  for (const counts of [{ ...summary, total: 0 }, { ...summary, skipped: 1 }, { ...summary, not_supported: 1 }, { ...summary, warning: 1 }]) {
    assert.equal(model.dashboardStatus({ overall_status: "PASS", summary: counts }), "WARNING");
  }
  assert.equal(model.dashboardStatus({ overall_status: "PASS", summary, coverage: { not_reached_stages: ["data"] } }), "WARNING");
});

test("latest report is selected by timestamp without mutating the API list", () => {
  const reports = [{ generated_at: "2026-09-06T12:00:00Z" }, { generated_at: "2026-09-07T12:00:00Z" }];
  assert.equal(model.newestReports(reports)[0], reports[1]);
  assert.equal(reports[0].generated_at, "2026-09-06T12:00:00Z");
});