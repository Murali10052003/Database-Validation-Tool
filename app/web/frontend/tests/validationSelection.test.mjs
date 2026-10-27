import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/validation/validationSelection.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("presets match supported backend checks", () => {
  assert.deepEqual(model.presetChecks("quick"), ["schema", "row_count"]);
  assert.equal(model.presetChecks("standard").length, 11);
  assert.equal(model.presetChecks("full").length, 14);
  assert.equal(new Set(model.presetChecks("full")).size, 14);
  assert.ok(model.presetChecks("full").includes("checksum"));
  assert.ok(!model.presetChecks("standard").includes("checksum"));
});

test("object tokens are trimmed and deduplicated without turning empty into a wildcard", () => {
  assert.deepEqual(model.parseObjects(" HR.T, ,HR.T, HR.V "), ["HR.T", "HR.V"]);
  assert.deepEqual(model.parseObjects(" , "), []);
  assert.equal(model.objectInScope("HR.T", []), false);
  assert.equal(model.objectInScope("HR.T", ["hr"]), true);
  assert.equal(model.objectInScope("HR.T", ["hr.t"]), true);
  assert.equal(model.objectInScope("HR.TWO", ["HR.T"]), false);
});

test("scope retains source names and unmatched tables", () => {
  const rows = model.scopeRows({ schema_matches: [{ source: "HR", target: "public", matched_tables: [{ source: "T", target: "renamed" }], unmatched_source_tables: ["OTHER"] }] });
  assert.deepEqual(rows.map(row => row.source), ["HR.T", "HR.OTHER"]);
  assert.equal(rows[0].target, "renamed");
  assert.equal(rows[1].target, "");
});

test("schema mapping preserves blank skips without choosing ambiguous candidates", () => {
  const plan = {schema_matches: [{source: "HR", target: "hr"}, {source: "SYS", target: ""}],
    unmatched_source_schemas: ["OTHER"], ambiguous_schemas: [{source: "sales", candidates: ["Sales", "SALES"]}]};
  assert.deepEqual(model.schemaMapping(plan), {HR: "hr", SYS: "", OTHER: "", sales: ""});
  assert.deepEqual(model.schemaMapping(plan, {hr: "  ", OTHER: " analytics "}),
    {HR: "", SYS: "", OTHER: "analytics", sales: ""});
});

test("schema badges describe current resolved names, not saved-mapping provenance", () => {
  const targets = ["hr", "analytics", "Sales", "SALES"];
  assert.equal(model.schemaMatchType("HR", "hr", targets), "case_insensitive");
  assert.equal(model.schemaMatchType("hr", "hr", targets), "exact");
  assert.equal(model.schemaMatchType("HR", "analytics", targets), "explicit");
  assert.equal(model.schemaMatchType("HR", " ", targets), "unmatched");
  assert.equal(model.schemaMatchType("OTHER", "OTHER", targets), "unmatched");
  assert.equal(model.schemaMatchType("sales", "sales", targets), "ambiguous");
  assert.equal(model.schemaMatchType("sales", "Sales", targets), "case_insensitive");
});
test("discovery requires an explicit schema on both sides", () => {
  assert.equal(model.scopeReady(["HR"], ["hr"]), true);
  assert.equal(model.scopeReady([], ["hr"]), false);
  assert.equal(model.scopeReady(["HR"], []), false);
});

test("schema selection toggles without mutating and keeps unlisted selections visible", () => {
  const selected = ["HR"];
  assert.deepEqual(model.toggleSchema(selected, "SALES"), ["HR", "SALES"]);
  assert.deepEqual(model.toggleSchema(["HR", "SALES"], "HR"), ["SALES"]);
  assert.deepEqual(selected, ["HR"]);
  assert.deepEqual(model.scopeSelection(["OLD"], ["HR", "SALES"]), ["HR", "SALES", "OLD"]);
  assert.deepEqual(model.scopeSelection(["HR"], null), ["HR"]);
});

test("names-only plans use live scoped discovery instead of refresh and report their scope", () => {
  const scoped = {metadata_complete: false, source_scope: ["MIGRATION_TEST"], target_scope: ["migration_test"], schema_matches: [], unmatched_target_schemas: []};
  assert.equal(model.metadataMode(scoped), "full");
  assert.deepEqual(model.planScope(scoped), {source: ["MIGRATION_TEST"], target: ["migration_test"]});
  assert.equal(model.metadataMode({metadata_complete: true}), "refresh");
  assert.equal(model.metadataMode({}), "refresh");
  const legacy = {schema_matches: [{source: "HR", target: "hr", match_type: "case_insensitive"}, {source: "SKIP", target: "", match_type: "unmatched"}], unmatched_target_schemas: ["extra"]};
  assert.deepEqual(model.planScope(legacy), {source: ["HR", "SKIP"], target: ["hr", "extra"]});
});

test("system schemas are recognised per engine and hidden unless requested", () => {
  assert.equal(model.isSystemSchema("XS$NULL", "oracle"), true);
  assert.equal(model.isSystemSchema("vecsys", "oracle"), true);
  assert.equal(model.isSystemSchema("APEX_240100", "oracle"), true);
  assert.equal(model.isSystemSchema("HR", "oracle"), false);
  assert.equal(model.isSystemSchema("pg_catalog", "azure_postgresql"), true);
  assert.equal(model.isSystemSchema("public", "azure_postgresql"), false);
  assert.equal(model.isSystemSchema("sys", "sqlserver"), true);
  assert.equal(model.isSystemSchema("performance_schema", "mysql"), true);
  assert.equal(model.isSystemSchema("performance_schema", "azure_mysql"), true);
  assert.equal(model.isSystemSchema("appdb", "azure_mysql"), false);
  assert.equal(model.isSystemSchema("SYS", undefined), false);
  const names = ["HR", "SYS", "SALES", "XS$NULL", "hr_archive"];
  assert.deepEqual(model.filterSchemas(names, {query: "", showSystem: false, engine: "oracle"}), ["HR", "SALES", "hr_archive"]);
  assert.deepEqual(model.filterSchemas(names, {query: "", showSystem: true, engine: "oracle"}), names);
  assert.deepEqual(model.filterSchemas(names, {query: " hr ", showSystem: false, engine: "oracle"}), ["HR", "hr_archive"]);
});

test("schema patterns accept wildcards and lists case-insensitively without regex surprises", () => {
  const names = ["HR", "HR_ARCHIVE", "SALES", "A.B", "AXB", "APP_SVC_01"];
  assert.deepEqual(model.matchSchemas(names, "HR*"), ["HR", "HR_ARCHIVE"]);
  assert.deepEqual(model.matchSchemas(names, "hr, sales"), ["HR", "SALES"]);
  assert.deepEqual(model.matchSchemas(names, "A.B"), ["A.B"]);
  assert.deepEqual(model.matchSchemas(names, "APP_SVC_0?"), ["APP_SVC_01"]);
  assert.deepEqual(model.matchSchemas(names, "   "), []);
  assert.deepEqual(model.matchSchemas(names, "("), []);
});

test("bulk selection helpers add and invert without duplicating or touching hidden choices", () => {
  assert.deepEqual(model.addSchemas(["HR"], ["HR", "SALES"]), ["HR", "SALES"]);
  assert.deepEqual(model.invertSchemas(["HR", "SYS"], ["HR", "SALES"]), ["SYS", "SALES"]);
  const selected = ["HR"];
  model.invertSchemas(selected, ["HR"]);
  assert.deepEqual(selected, ["HR"]);
});

test("target suggestions mirror the source selection and skip names already chosen", () => {
  const available = ["hr", "sales", "Finance", "public"];
  assert.deepEqual(model.suggestTargetSchemas(["HR", "FINANCE", "MISSING"], available, []), ["hr", "Finance"]);
  assert.deepEqual(model.suggestTargetSchemas(["HR", "SALES"], available, ["hr"]), ["sales"]);
  assert.deepEqual(model.suggestTargetSchemas(["HR"], null, []), []);
});
