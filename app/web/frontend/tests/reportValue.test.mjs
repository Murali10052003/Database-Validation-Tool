import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/validation/reportValue.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { reportValue } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("missing report values are distinct from zero, false and empty strings", () => {
  assert.equal(reportValue(undefined), "Not recorded");
  assert.equal(reportValue(null), "Not recorded");
  assert.equal(reportValue(0), "0");
  assert.equal(reportValue(false), "false");
  assert.equal(reportValue(""), '""');
});

test("structured report evidence preserves every field without truncation", () => {
  const value = { type: "VARCHAR", length: 60, nullable: false, values: [0, null, ""] };
  assert.deepEqual(JSON.parse(reportValue(value)), value);
  const longValue = "x".repeat(10000);
  assert.equal(reportValue(longValue), longValue);
});