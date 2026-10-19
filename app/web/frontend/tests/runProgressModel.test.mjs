import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/validation/runProgressModel.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("UI progress hides custom query without removing other stages or modifying logs", () => {
  const events = ["connectivity", "row_count", "custom_query", "aggregate", "checksum", "checksum"]
    .map(stage => ({ stage, event: "stage_finished", details: {} }));
  const original = structuredClone(events);
  assert.deepEqual(model.visibleRunStages(events), ["connectivity", "row_count", "aggregate", "checksum"]);
  assert.deepEqual(events, original);
  assert.deepEqual(model.visibleRunStages([]), []);
});