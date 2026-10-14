import { useEffect, useMemo, useRef, useState } from "react";
import type { PlanResponse } from "../../api/types";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { applyImport, buildReview, reviewCounts, rowVisible, scopeMatcher, setInclusion, targetOnlyTables, toCsv, withOverride, type ReviewGroup, type ReviewRow, type ScopeState, type StatusFilter } from "./scopeReview";
import { globMatcher, parseObjects } from "./validationSelection";

interface Props {
  plan: PlanResponse;
  all: boolean;
  included: string;
  excluded: string;
  schemas: Record<string, string>;
  tables: Record<string, string>;
  onScope: (all: boolean, included: string) => void;
  onExcluded: (value: string) => void;
  onTables: (tables: Record<string, string>) => void;
}

const PAGE = 25;
const STATE_BADGE = {
  matched: { tone: "success", label: "Matched" },
  mapped: { tone: "info", label: "Manual" },
  review: { tone: "warning", label: "Needs review" },
  "source-only": { tone: "danger", label: "Source only" },
} as const;

function TriCheckbox({ checked, indeterminate, label, onChange }: { checked: boolean; indeterminate: boolean; label: string; onChange: (checked: boolean) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate; }, [indeterminate]);
  return <input ref={ref} type="checkbox" aria-label={label} checked={checked} onChange={event => onChange(event.target.checked)} />;
}

interface PickerProps {
  row: ReviewRow;
  group: ReviewGroup;
  pool: Map<string, string>;
  listId: string;
  autoFocus: boolean;
  onCommit: (target: string | null) => void;
  onCancel: () => void;
}

// Free text limited to unmapped target tables; commits on a datalist pick, Enter or blur.
function TargetPicker({ row, group, pool, listId, autoFocus, onCommit, onCancel }: PickerProps) {
  const [value, setValue] = useState(autoFocus ? row.target : "");
  const [invalid, setInvalid] = useState(false);
  const resolve = (text: string) => {
    const name = text.trim();
    return pool.get((name.includes(".") ? name : `${group.targetSchema}.${name}`).toLowerCase()) ?? null;
  };
  function commit(text: string) {
    if (!text.trim()) { if (row.state === "mapped") onCommit(null); else onCancel(); return; }
    if (text.trim().toLowerCase() === row.target.toLowerCase()) { onCancel(); return; }
    const target = resolve(text);
    if (target) onCommit(target); else setInvalid(true);
  }
  return (
    <input
      className={`input rv-input${invalid ? " is-invalid" : ""}`} list={listId} value={value} autoFocus={autoFocus} aria-invalid={invalid}
      aria-label={`Target for ${row.id}`} placeholder="Choose an unmapped target table…" title={invalid ? "Not an unmapped target table in the matched schema" : undefined}
      onChange={event => {
        setValue(event.target.value); setInvalid(false);
        // Typing is an InputEvent; picking from the datalist is not (or is a replacement).
        const native = event.nativeEvent as InputEvent;
        if ((!(native instanceof InputEvent) || native.inputType === "insertReplacementText") && resolve(event.target.value)) commit(event.target.value);
      }}
      onBlur={event => commit(event.target.value)}
      onKeyDown={event => {
        if (event.key === "Enter") { event.preventDefault(); commit(value); }
        if (event.key === "Escape") onCancel();
      }}
    />
  );
}

export function ObjectScopePanel({ plan, all, included, excluded, schemas, tables, onScope, onExcluded, onTables }: Props) {
  const scope = useMemo<ScopeState>(() => ({ all, included: parseObjects(included), excluded: parseObjects(excluded) }), [all, included, excluded]);
  const groups = useMemo(() => buildReview(plan, schemas, tables), [plan, schemas, tables]);
  const isIncluded = useMemo(() => scopeMatcher(scope), [scope]);
  const counts = useMemo(() => reviewCounts(groups, scope), [groups, scope]);
  const pool = useMemo(() => new Map(groups.flatMap(group => group.unmapped.map(table => [`${group.targetSchema}.${table}`.toLowerCase(), `${group.targetSchema}.${table}`] as const))), [groups]);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const [schemaFilter, setSchemaFilter] = useState("all");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [limits, setLimits] = useState<Record<string, number>>({});
  const [editing, setEditing] = useState<Set<string>>(new Set());
  const [note, setNote] = useState<{ text: string; details: string[] } | null>(null);
  const [pattern, setPattern] = useState("");
  const [showTargetOnly, setShowTargetOnly] = useState(false);
  const menu = useRef<HTMLDetailsElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const importInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setFilter("all"); setQuery(""); setSchemaFilter("all"); setLimits({}); setEditing(new Set()); setNote(null);
    setOpen(new Set(plan.schema_matches.slice(0, plan.schema_matches.length <= 3 ? undefined : 1).map(match => match.source)));
  }, [plan]);
  useEffect(() => {
    if (showTargetOnly && !dialog.current?.open) dialog.current?.showModal();
    if (!showTargetOnly && dialog.current?.open) dialog.current.close();
  }, [showTargetOnly]);

  const filtering = filter !== "all" || query.trim() !== "";
  const shown = useMemo(() => new Map(groups.map(group => [group.schema, schemaFilter !== "all" && schemaFilter !== group.schema ? [] : group.rows.filter(row => rowVisible(row, isIncluded(row.id), filter, query))])), [groups, schemaFilter, isIncluded, filter, query]);
  const shownRows = useMemo(() => [...shown.values()].flat(), [shown]);
  const apply = (next: ScopeState) => { onScope(next.all, next.included.join(", ")); onExcluded(next.excluded.join(", ")); };
  const flag = (rows: ReviewRow[], checked: boolean) => apply(setInclusion(scope, rows.map(row => row.id), checked));

  function bulk(action: string) {
    const groupOf = new Map(groups.map(group => [group.schema, group]));
    let changed = 0;
    const mark = (rows: ReviewRow[], checked: boolean) => { changed += rows.filter(row => isIncluded(row.id) !== checked).length; return rows.map(row => row.id); };
    if (action === "include") apply(setInclusion(scope, mark(shownRows, true), true));
    if (action === "exclude") apply(setInclusion(scope, mark(shownRows, false), false));
    if (action === "exclude-source-only") apply(setInclusion(scope, mark(shownRows.filter(row => row.state === "source-only"), false), false));
    if (action === "matched-only") {
      const keep = shownRows.filter(row => row.state === "matched" || row.state === "mapped"), drop = shownRows.filter(row => !keep.includes(row));
      apply(setInclusion(setInclusion(scope, mark(keep, true), true), mark(drop, false), false));
    }
    if (action === "pattern") {
      const matches = globMatcher(pattern);
      if (!matches) return;
      apply(setInclusion(scope, mark(shownRows.filter(row => matches(row.table) || matches(row.id)), false), false));
    }
    if (action === "accept") {
      const rows = shownRows.filter(row => row.state === "review" && (row.suggestion?.score ?? 0) >= 0.9);
      onTables(rows.reduce((next, row) => withOverride(next, row.id, `${groupOf.get(row.schema)!.targetSchema}.${row.suggestion!.target}`), tables));
      changed = rows.length;
    }
    if (menu.current) menu.current.open = false;
    setNote({ text: `${changed} row${changed === 1 ? "" : "s"} updated`, details: [] });
  }

  const stopEditing = (id: string) => setEditing(current => {
    if (!current.has(id)) return current;
    const next = new Set(current);
    next.delete(id);
    return next;
  });
  function commit(row: ReviewRow, target: string | null) {
    onTables(withOverride(tables, row.id, target));
    stopEditing(row.id);
  }

  function exportCsv() {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([toCsv(groups, scope)], { type: "text/csv" }));
    link.download = "table-mapping.csv";
    link.click();
    URL.revokeObjectURL(link.href);
    setNote({ text: `Exported ${counts.total} rows`, details: [] });
  }
  async function importCsv(file: File | undefined) {
    if (!file) return;
    try {
      const result = applyImport(groups, scope, tables, await file.text());
      onTables(result.overrides);
      apply(result.scope);
      setNote({ text: `Imported ${result.applied} row${result.applied === 1 ? "" : "s"}; ${result.rejected.length} could not be applied`, details: result.rejected.slice(0, 20) });
    } catch (error) {
      setNote({ text: error instanceof Error ? error.message : "The CSV could not be read.", details: [] });
    }
    if (importInput.current) importInput.current.value = "";
  }

  const tiles: [StatusFilter | "target-only", string, string, number][] = [
    ["matched", "success", "Matched", counts.matched],
    ["review", "warning", "Needs review", counts.review],
    ["source-only", "danger", "Source only", counts.sourceOnly],
    ["target-only", "info", "Target only", counts.targetOnly],
    ["excluded", "muted", "Excluded", counts.excluded],
  ];

  return <section className="object-scope" aria-label="Object scope">
    <div className="scope-heading">
      <h3>Object scope</h3>
      <span>{counts.included} of {counts.total} tables selected{counts.review + counts.sourceOnly > 0 ? ` · ${counts.review + counts.sourceOnly} need attention` : ""}</span>
      <div className="scope-actions">
        <Button size="sm" onClick={() => { onScope(true, ""); onExcluded(""); }}>Include all</Button>
        <Button size="sm" onClick={() => { onScope(false, ""); onExcluded(""); }}>Clear selection</Button>
      </div>
    </div>

    <div className="rv-tiles">
      {tiles.map(([key, tone, label, value]) => (
        <button key={key} type="button" className={`rv-tile rv-tile--${tone}${filter === key ? " is-active" : ""}`} aria-pressed={filter === key}
          onClick={() => key === "target-only" ? setShowTargetOnly(true) : setFilter(filter === key ? "all" : key)}>
          <strong>{value}</strong><span>{label}</span>
        </button>
      ))}
    </div>

    <div className="rv-toolbar">
      <input type="search" className="input rv-search" placeholder="Search tables" aria-label="Search tables" value={query} onChange={event => setQuery(event.target.value)} />
      <select className="input select rv-select" aria-label="Filter by status" value={filter} onChange={event => setFilter(event.target.value as StatusFilter)}>
        <option value="all">All statuses</option><option value="attention">Needs attention</option><option value="matched">Matched</option>
        <option value="review">Needs review</option><option value="source-only">Source only</option><option value="excluded">Excluded</option>
      </select>
      <select className="input select rv-select" aria-label="Filter by schema" value={schemaFilter} onChange={event => setSchemaFilter(event.target.value)}>
        <option value="all">All schemas</option>
        {groups.map(group => <option key={group.schema} value={group.schema}>{group.schema}</option>)}
      </select>
      <details className="rv-menu" ref={menu}>
        <summary className="btn btn--secondary btn--sm">Bulk actions</summary>
        <div className="rv-menu__panel">
          <p className="field__hint">Applies to the {shownRows.length} shown row{shownRows.length === 1 ? "" : "s"}.</p>
          <button type="button" onClick={() => bulk("include")}>Include shown</button>
          <button type="button" onClick={() => bulk("exclude")}>Exclude shown</button>
          <button type="button" onClick={() => bulk("matched-only")}>Include matched only</button>
          <button type="button" onClick={() => bulk("exclude-source-only")}>Exclude source-only</button>
          <button type="button" onClick={() => bulk("accept")}>Accept suggestions of 90% or more</button>
          <div className="rv-menu__row">
            <input className="input rv-input" placeholder="Exclude pattern: *_LOG, TMP_*" aria-label="Exclude pattern" value={pattern} onChange={event => setPattern(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); bulk("pattern"); } }} />
            <Button size="sm" disabled={!pattern.trim()} onClick={() => bulk("pattern")}>Apply</Button>
          </div>
        </div>
      </details>
      <Button size="sm" onClick={exportCsv} disabled={!counts.total}>Export CSV</Button>
      <Button size="sm" onClick={() => importInput.current?.click()} disabled={!counts.total}>Import CSV</Button>
      <input ref={importInput} type="file" accept=".csv,text/csv" hidden onChange={event => void importCsv(event.target.files?.[0])} />
    </div>
    {note && <div className="field__hint" role="status">{note.text}{note.details.length > 0 && <details><summary>Details</summary><ul>{note.details.map(detail => <li key={detail}>{detail}</li>)}</ul></details>}</div>}

    <div className="rv-groups">
      {groups.map((group, index) => {
        const rows = shown.get(group.schema) ?? [];
        if (schemaFilter !== "all" && schemaFilter !== group.schema) return null;
        if (filtering && !rows.length) return null;
        const total = group.rows.length || 1;
        const ok = group.rows.filter(row => row.state === "matched" || row.state === "mapped").length;
        const review = group.rows.filter(row => row.state === "review").length;
        const isOpen = open.has(group.schema) || filtering;
        const limit = limits[group.schema] ?? PAGE;
        const on = rows.filter(row => isIncluded(row.id)).length;
        const listId = `rv-targets-${index}`;
        return <section className="rv-group" key={group.schema}>
          <div className="rv-group__head">
            <button type="button" className="rv-chevron" aria-expanded={isOpen} aria-label={`${isOpen ? "Collapse" : "Expand"} ${group.schema}`} disabled={filtering}
              onClick={() => setOpen(current => { const next = new Set(current); next.has(group.schema) ? next.delete(group.schema) : next.add(group.schema); return next; })}>▸</button>
            <TriCheckbox label={`Include all shown tables in ${group.schema}`} checked={rows.length > 0 && on === rows.length} indeterminate={on > 0 && on < rows.length} onChange={checked => flag(rows, checked)} />
            <strong>{group.schema}</strong><span className="rv-muted">→</span>
            {group.targetSchema ? <span>{group.targetSchema}</span> : <Badge tone="danger">no target schema</Badge>}
            <span className="rv-muted">{group.rows.length} tables · {ok} matched · {review} review · {group.rows.length - ok - review} source only</span>
            <span className="rv-bar" aria-hidden><i className="ok" style={{ width: `${ok / total * 100}%` }} /><i className="warn" style={{ width: `${review / total * 100}%` }} /><i className="bad" style={{ width: `${(total - ok - review) / total * 100}%` }} /></span>
          </div>
          {isOpen && <>
            <datalist id={listId}>{group.unmapped.map(table => <option key={table} value={table} />)}</datalist>
            {rows.slice(0, limit).map(row => {
              const badge = STATE_BADGE[row.state], on = isIncluded(row.id);
              return <div className={`rv-row${on ? "" : " is-off"}`} key={row.id}>
                <input type="checkbox" aria-label={`Include ${row.id}`} checked={on} onChange={event => flag([row], event.target.checked)} />
                <span className="rv-table" title={row.table}>{row.table}</span>
                <span className="rv-muted" aria-hidden>→</span>
                <span className="rv-target">
                  {editing.has(row.id) || row.state === "source-only"
                    ? <><TargetPicker row={row} group={group} pool={pool} listId={listId} autoFocus={editing.has(row.id)} onCommit={target => commit(row, target)} onCancel={() => stopEditing(row.id)} />{editing.has(row.id) && <button type="button" className="rv-link" onClick={() => stopEditing(row.id)}>Cancel</button>}</>
                    : row.state === "review"
                      ? <><span>{row.suggestion!.target}</span><span className="rv-score">{Math.round(row.suggestion!.score * 100)}% similar</span>
                          <Button size="sm" variant="primary" onClick={() => commit(row, `${group.targetSchema}.${row.suggestion!.target}`)}>Accept</Button>
                          <Button size="sm" onClick={() => setEditing(current => new Set(current).add(row.id))}>Change</Button></>
                      : <><span>{row.target}</span>
                          <button type="button" className="rv-link" onClick={() => setEditing(current => new Set(current).add(row.id))}>Change</button>
                          {row.state === "mapped" && <button type="button" className="rv-link" onClick={() => commit(row, null)}>Reset</button>}</>}
                </span>
                <Badge tone={badge.tone}>{badge.label}</Badge>
              </div>;
            })}
            {rows.length > limit && <div className="rv-more">Showing {limit} of {rows.length}
              <Button size="sm" onClick={() => setLimits(current => ({ ...current, [group.schema]: limit + PAGE }))}>Show {PAGE} more</Button>
              <Button size="sm" onClick={() => setLimits(current => ({ ...current, [group.schema]: rows.length }))}>Show all</Button></div>}
            {rows.length === 0 && <p className="rv-more">No tables match the current filter.</p>}
          </>}
        </section>;
      })}
      {counts.total === 0 && <p className="workflow-empty">No tables in matched schemas.</p>}
      {counts.total > 0 && shownRows.length === 0 && <p className="workflow-empty">No tables match the current filters.</p>}
    </div>

    <details className="workflow-details">
      <summary>Edit included and excluded objects as text</summary>
      <div className="scope-fields">
        <label className="field"><span className="field__label">Included objects</span><input className="input" placeholder={all ? "All objects" : "SCHEMA.TABLE, SCHEMA.OTHER"} value={included} onChange={event => onScope(false, event.target.value)} /></label>
        <label className="field"><span className="field__label">Excluded objects</span><input className="input" placeholder="SCHEMA.TABLE, SCHEMA.OTHER" value={excluded} onChange={event => onExcluded(event.target.value)} /></label>
      </div>
    </details>
    {counts.total > 0 && counts.included === 0 && <p role="status">No tables are selected for validation.</p>}

    <dialog ref={dialog} className="rv-dialog" aria-labelledby="rv-target-only" onClose={() => setShowTargetOnly(false)}>
      <div className="rv-dialog__head"><h3 id="rv-target-only">Target-only tables</h3><Button size="sm" onClick={() => setShowTargetOnly(false)}>Close</Button></div>
      <p className="field__hint">These exist on the target but not on the source. They are listed for awareness and are not validated.</p>
      {groups.filter(group => group.targetSchema).map(group => {
        const names = targetOnlyTables(group);
        return <div key={group.schema}><h4>{group.targetSchema} <span className="rv-score">{names.length}</span></h4>{names.length ? <p className="rv-chips">{names.map(name => <code key={name}>{name}</code>)}</p> : <p className="rv-muted">None</p>}</div>;
      })}
    </dialog>
  </section>;
}
