import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/data/dbTypes.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { SOURCE_DB_TYPES, TARGET_DB_TYPES } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("database dropdowns omit untested SQL Server and Azure SQL options", () => {
  assert.deepEqual(SOURCE_DB_TYPES.map(({ value }) => value), [
    "oracle", "mysql", "azure_postgresql", "azure_mysql",
  ]);
  assert.deepEqual(TARGET_DB_TYPES.map(({ value }) => value), [
    "azure_postgresql", "azure_mysql",
  ]);
});
