import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/validation/scopeReview.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const plan = {
  schema_matches: [
    {
      source: "HR", target: "hr", match_type: "case_insensitive",
      matched_tables: [{ source: "EMPLOYEE", target: "employee", match_type: "case_insensitive" }, { source: "DEPARTMENT", target: "department", match_type: "case_insensitive" }],
      unmatched_source_tables: ["CUSTOMER_ITEMS", "ACCOUNT"],
      unmatched_target_tables: ["customer_item", "audit_log"],
    },
    { source: "SALES", target: "", match_type: "unmatched", matched_tables: [], unmatched_source_tables: ["ORDERS"], unmatched_target_tables: [] },
  ],
};
const all = { all: true, included: [], excluded: [] };

test("groups keep real match types and suggest renamed tables one-to-one", () => {
  const [hr, sales] = model.buildReview(plan, { HR: "hr" }, {});
  assert.deepEqual(hr.rows.map(row => [row.table, row.state]), [["ACCOUNT", "source-only"], ["CUSTOMER_ITEMS", "review"], ["DEPARTMENT", "matched"], ["EMPLOYEE", "matched"]]);
  assert.equal(hr.rows[1].suggestion.target, "customer_item");
  assert.ok(hr.rows[1].suggestion.score > 0.9);
  assert.equal(hr.rows[2].target, "hr.department");
  assert.deepEqual(hr.unmapped, ["audit_log", "customer_item"]);
  assert.deepEqual(model.targetOnlyTables(hr), ["audit_log"]);
  assert.equal(sales.targetSchema, "");
  assert.deepEqual(sales.rows.map(row => row.state), ["source-only"]);
});

test("table overrides become manual mappings and free or consume target tables", () => {
  const [hr] = model.buildReview(plan, { HR: "hr" }, { "hr.account": "hr.audit_log", "HR.EMPLOYEE": "hr.customer_item" });
  const byTable = Object.fromEntries(hr.rows.map(row => [row.table, row]));
  assert.deepEqual([byTable.ACCOUNT.state, byTable.ACCOUNT.target], ["mapped", "hr.audit_log"]);
  assert.equal(byTable.EMPLOYEE.state, "mapped");
  assert.equal(byTable.CUSTOMER_ITEMS.state, "source-only");
  assert.deepEqual(hr.unmapped, ["employee"]);
  const same = model.buildReview(plan, {}, { "HR.EMPLOYEE": "hr.EMPLOYEE" })[0].rows.find(row => row.table === "EMPLOYEE");
  assert.equal(same.state, "matched");
});

test("suggestions are skipped for weak matches and oversized inputs", () => {
  assert.equal(model.suggestTargets(["INVOICE"], ["tbl_invoice_archive"]).size, 0);
  assert.equal(model.suggestTargets(["A"], ["b"]).size, 0);
  const many = Array.from({ length: 300 }, (_, index) => `T${index}`);
  assert.equal(model.suggestTargets(many, many.map(name => name.toLowerCase())).size, 0);
  const picked = model.suggestTargets(["ORDER_ITEM", "ORDER_ITEMS"], ["order_items"]);
  assert.equal(picked.get("ORDER_ITEMS").target, "order_items");
  assert.equal(picked.has("ORDER_ITEM"), false);
});

test("inclusion respects exclusions, schema-level names and case without mutating", () => {
  const scope = { all: true, included: [], excluded: ["HR.ACCOUNT", "sales"] };
  const matches = model.scopeMatcher(scope);
  assert.deepEqual(["HR.EMPLOYEE", "hr.account", "SALES.ORDERS"].map(matches), [true, false, false]);
  assert.equal(model.scopeMatcher({ all: false, included: ["hr"], excluded: [] })("HR.EMPLOYEE"), true);
  assert.equal(model.scopeMatcher({ all: false, included: [], excluded: [] })("HR.EMPLOYEE"), false);
  const unchecked = model.setInclusion(all, ["HR.EMPLOYEE"], false);
  assert.deepEqual(unchecked, { all: true, included: [], excluded: ["HR.EMPLOYEE"] });
  assert.deepEqual(all, { all: true, included: [], excluded: [] });
  assert.deepEqual(model.setInclusion(unchecked, ["hr.employee"], true), all);
});

test("explicit selections add and remove exact names and exclude from schema-level includes", () => {
  const none = { all: false, included: [], excluded: [] };
  const added = model.setInclusion(none, ["HR.A", "HR.B"], true);
  assert.deepEqual(added.included, ["HR.A", "HR.B"]);
  assert.deepEqual(model.setInclusion(added, ["HR.A"], false), { all: false, included: ["HR.B"], excluded: [] });
  const schema = { all: false, included: ["HR"], excluded: [] };
  assert.deepEqual(model.setInclusion(schema, ["HR.A"], false), { all: false, included: ["HR"], excluded: ["HR.A"] });
  assert.deepEqual(model.setInclusion({ all: false, included: ["HR"], excluded: ["HR.A"] }, ["HR.A"], true), schema);
  assert.deepEqual(model.setInclusion(schema, ["HR.B"], true), schema);
});

test("counts and filters describe what needs attention", () => {
  const groups = model.buildReview(plan, { HR: "hr" }, {});
  const counts = model.reviewCounts(groups, { all: true, included: [], excluded: ["HR.ACCOUNT"] });
  assert.deepEqual(counts, { total: 5, matched: 2, review: 1, sourceOnly: 2, targetOnly: 1, included: 4, excluded: 1 });
  const row = groups[0].rows[1];
  assert.equal(model.rowVisible(row, true, "attention", ""), true);
  assert.equal(model.rowVisible(row, true, "matched", ""), false);
  assert.equal(model.rowVisible(row, false, "excluded", ""), true);
  assert.equal(model.rowVisible(row, true, "all", " ITEM "), true);
  assert.equal(model.rowVisible(row, true, "all", "payment"), false);
});

test("csv fields survive quotes, commas and line endings", () => {
  assert.deepEqual(model.parseCsv('a,"b,c","d ""q"""\r\nx,y,z\n\n'), [["a", "b,c", 'd "q"'], ["x", "y", "z"]]);
  assert.deepEqual(model.parseCsv("a,b"), [["a", "b"]]);
});

test("export then import round-trips and applies edits safely", () => {
  const groups = model.buildReview(plan, { HR: "hr" }, {});
  const csv = model.toCsv(groups, { all: true, included: [], excluded: ["HR.EMPLOYEE"] });
  assert.match(csv, /^schema,source_table,target_table,suggested_target,status,included\n/);
  assert.match(csv, /HR,CUSTOMER_ITEMS,,hr\.customer_item,review,true/);
  assert.match(csv, /HR,EMPLOYEE,hr\.employee,,matched,false/);
  const unchanged = model.applyImport(groups, { all: true, included: [], excluded: ["HR.EMPLOYEE"] }, {}, csv);
  assert.deepEqual(unchanged.overrides, {});
  assert.deepEqual(unchanged.scope.excluded, ["HR.EMPLOYEE"]);

  const edited = [
    "schema,source_table,target_table,included",
    "HR,CUSTOMER_ITEMS,customer_item,true",
    "HR,ACCOUNT,missing_table,true",
    "HR,EMPLOYEE,,false",
    "HR,NOPE,x,true",
  ].join("\n");
  const result = model.applyImport(groups, all, {}, edited);
  assert.deepEqual(result.overrides, { "HR.CUSTOMER_ITEMS": "hr.customer_item" });
  assert.deepEqual(result.scope.excluded, ["HR.EMPLOYEE"]);
  assert.equal(result.rejected.length, 2);
  assert.throws(() => model.applyImport(groups, all, {}, "a,b\n1,2"), /schema and source_table/);
  const reset = model.applyImport(model.buildReview(plan, { HR: "hr" }, result.overrides), all, result.overrides, "schema,source_table,target_table\nHR,CUSTOMER_ITEMS,");
  assert.deepEqual(reset.overrides, {});
});

test("overrides replace case-insensitively without duplicating keys", () => {
  assert.deepEqual(model.withOverride({ "hr.t": "a.b" }, "HR.T", "a.c"), { "HR.T": "a.c" });
  assert.deepEqual(model.withOverride({ "hr.t": "a.b", x: "y" }, "HR.T", null), { x: "y" });
});
