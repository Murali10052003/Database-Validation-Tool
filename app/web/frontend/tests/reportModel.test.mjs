import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/validation/reportModel.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const empty = { total: 0, passed: 0, failed: 0, warning: 0, error: 0, skipped: 0, notSupported: 0 };

test("custom queries are hidden when empty but actual results remain visible", () => {
  const summary = { total: 1, passed: 0, failed: 1, warning: 0, error: 0, skipped: 0, not_supported: 0 };
  const result = { check_id: "checksum:HR.T", category: "CHECKSUM", status: "FAIL", severity: "HIGH", differences: [] };
  const current = model.buildReportModel({ results: [result], summary });
  assert.equal(current.categories.some(group => group.meta.id === "custom"), false);
  const custom = { ...result, check_id: "custom_query:revenue", category: "CUSTOM_QUERY" };
  const configured = model.buildReportModel({ results: [custom], summary });
  assert.equal(configured.categories.find(group => group.meta.id === "custom").counts.failed, 1);
  assert.deepEqual(configured.issues, [custom]);
});

test("sample category only appears for historical sampling results", () => {
  const summary = { total: 1, passed: 1, failed: 0, warning: 0, error: 0, skipped: 0, not_supported: 0 };
  const result = { check_id: "checksum:HR.T", category: "CHECKSUM", status: "PASS", differences: [] };
  const current = model.buildReportModel({ results: [result], summary });
  assert.equal(current.categories.some(group => group.meta.id === "samples"), false);
  assert.equal(current.categories.find(group => group.meta.id === "checksums").counts.total, 1);
  const historical = model.buildReportModel({ results: [{ ...result, check_id: "sample_data:HR.T", category: "SAMPLE_DATA" }], summary });
  assert.equal(historical.categories.find(group => group.meta.id === "samples").counts.total, 1);
});

test("incomplete and empty checks have no pass rate", () => {
  for (const counts of [empty, { ...empty, total: 1, skipped: 1 }, { ...empty, total: 1, notSupported: 1 }, { ...empty, total: 1, error: 1 }]) {
    assert.equal(model.healthPct(counts), null);
    assert.notEqual(model.groupStatus(counts), "PASS");
  }
  assert.equal(model.groupStatus({ ...empty, total: 2, passed: 1, notSupported: 1 }), "WARNING");
});

test("unsupported and skipped are separate", () => {
  assert.equal(model.matchesStatus({ status: "NOT_SUPPORTED" }, "SKIPPED"), false);
  assert.equal(model.matchesStatus({ status: "NOT_SUPPORTED" }, "NOT_SUPPORTED"), true);
});

test("all known categories leave the catch-all", () => {
  for (const category of ["VIEW", "ROUTINE", "TRIGGER", "PARTITION", "SAMPLE_DATA", "CUSTOM_QUERY", "COMPATIBILITY", "CONNECTIVITY"]) {
    assert.notEqual(model.categoryOf({ category }), "otherObjects");
  }
  assert.equal(model.categoryOf({ category: "SCHEMA", check_id: "discovery" }), "execution");
});

test("producer classification overrides legacy message heuristics", () => {
  assert.equal(model.categoryOf({ category: "COLUMN", classification: "datatype", status: "NOT_SUPPORTED", differences: [] }), "dataTypes");
  assert.equal(model.categoryOf({ category: "COLUMN", classification: "column_attributes", status: "FAIL", differences: ["type in unrelated text"] }), "columns");
});

test("each result appears once and blocking issues precede gaps", () => {
  const results = ["SKIPPED", "NOT_SUPPORTED", "WARNING", "FAIL", "ERROR", "PASS"].map((status) => ({
    check_id: status, category: "SAMPLE_DATA", status, severity: "HIGH", differences: [],
  }));
  const report = model.buildReportModel({ results, summary: {
    total: 6, skipped: 1, not_supported: 1, warning: 1, failed: 1, error: 1, passed: 1,
  } });
  assert.equal(report.categories.reduce((total, category) => total + category.checks.length, 0), 6);
  assert.deepEqual(report.issues.map((result) => result.status), ["ERROR", "FAIL", "WARNING", "NOT_SUPPORTED", "SKIPPED"]);
});