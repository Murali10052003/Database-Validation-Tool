import { useMemo, useState, type ReactNode } from "react";
import type { DatabaseType } from "../../api/types";
import { Button } from "../ui/Button";
import { addSchemas, filterSchemas, invertSchemas, isSystemSchema, matchSchemas, scopeSelection, toggleSchema } from "./validationSelection";

interface Props {
  label: string;
  engine?: DatabaseType;
  available: string[] | null;
  selected: string[];
  onChange: (selected: string[]) => void;
  action: ReactNode;
  suggested?: string[];
}

const PAGE = 100;

// Choose which schemas Discover & match should read on one side of the migration.
export function SchemaScopePanel({ label, engine, available, selected, onChange, action, suggested = [] }: Props) {
  const [query, setQuery] = useState("");
  const [showSystem, setShowSystem] = useState(false);
  const [limit, setLimit] = useState(PAGE);
  const [pattern, setPattern] = useState("");
  const [note, setNote] = useState("");
  const options = useMemo(() => scopeSelection(selected, available), [selected, available]);
  const shown = useMemo(() => filterSchemas(options, { query, showSystem, engine }), [options, query, showSystem, engine]);
  const hidden = showSystem ? 0 : options.filter(name => isSystemSchema(name, engine)).length;
  const chosen = useMemo(() => [...selected].sort((a, b) => a.localeCompare(b)), [selected]);
  const idle = options.length === 0;

  function applyPattern() {
    const pool = filterSchemas(options, { query: "", showSystem, engine });
    const matches = matchSchemas(pool, pattern);
    const added = matches.filter(name => !selected.includes(name)).length;
    onChange(addSchemas(selected, matches));
    setNote(matches.length ? `${added} schema${added === 1 ? "" : "s"} added` : hidden ? "No visible schema matches. Show system schemas to include those." : "No schema matches the pattern.");
  }

  return (
    <section className="schema-scope" aria-label={`${label} schemas`}>
      <div className="workflow-section-heading">
        <h4>{label} schemas</h4>
        <div className="scope-actions">{action}</div>
      </div>
      <div className="schema-scope__tools">
        <input type="search" className="input schema-scope__field" placeholder="Search schemas" aria-label={`Search ${label.toLowerCase()} schemas`} value={query} disabled={idle} onChange={event => { setQuery(event.target.value); setLimit(PAGE); }} />
        <label className="schema-scope__system">
          <input type="checkbox" checked={showSystem} disabled={idle} onChange={event => { setShowSystem(event.target.checked); setLimit(PAGE); }} />
          Show system schemas{hidden > 0 && <span className="field__hint"> ({hidden} hidden)</span>}
        </label>
      </div>
      <div className="schema-scope__tools">
        <Button size="sm" disabled={idle || !shown.length} onClick={() => { onChange(addSchemas(selected, shown)); setNote(""); }}>Select all shown</Button>
        <Button size="sm" disabled={idle || !shown.length} onClick={() => { onChange(invertSchemas(selected, shown)); setNote(""); }}>Invert</Button>
        <Button size="sm" disabled={!selected.length} onClick={() => { onChange([]); setNote(""); }}>Clear</Button>
        <input className="input schema-scope__field" placeholder="Pattern or list, e.g. HR*, SALES" aria-label={`${label} schema pattern`} value={pattern} disabled={idle} onChange={event => setPattern(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); applyPattern(); } }} />
        <Button size="sm" disabled={idle || !pattern.trim()} onClick={applyPattern}>Select</Button>
      </div>
      {note && <p className="field__hint" role="status">{note}</p>}
      {suggested.length > 0 && (
        <div className="schema-scope__suggest">
          <span>Matches your source selection: <strong>{suggested.slice(0, 4).join(", ")}{suggested.length > 4 ? ` +${suggested.length - 4} more` : ""}</strong></span>
          <Button size="sm" onClick={() => onChange(addSchemas(selected, suggested))}>Select {suggested.length}</Button>
        </div>
      )}
      <div className="schema-scope__dual">
        <div className="schema-scope__pane">
          <div className="schema-scope__pane-head">Available <span className="schema-scope__count">{idle ? 0 : `${shown.length} of ${options.length}`}</span></div>
          <div className="schema-scope__list" role="group" aria-label={`${label} schema selection`}>
            {idle
              ? <p className="schema-scope__empty">Load the schemas visible to this connection, then select the ones to discover.</p>
              : shown.length === 0
                ? <p className="schema-scope__empty">No schemas match the search.</p>
                : shown.slice(0, limit).map(name => (
                    <label key={name} className={`schema-row${selected.includes(name) ? " is-on" : ""}`}>
                      <input type="checkbox" checked={selected.includes(name)} onChange={() => { onChange(toggleSchema(selected, name)); setNote(""); }} />
                      <span className="schema-row__name" title={name}>{name}</span>
                      {isSystemSchema(name, engine) && <span className="schema-row__tag">system</span>}
                    </label>
                  ))}
            {shown.length > limit && <Button size="sm" className="schema-scope__more" onClick={() => setLimit(limit + PAGE)}>Show more ({shown.length - limit} remaining)</Button>}
          </div>
        </div>
        <div className="schema-scope__pane">
          <div className="schema-scope__pane-head">Selected <span className="schema-scope__count">{selected.length}</span></div>
          <div className="schema-scope__list" aria-label={`${label} selected schemas`}>
            {chosen.length === 0
              ? <p className="schema-scope__empty">No schema selected</p>
              : chosen.map(name => (
                  <div key={name} className="schema-row schema-row--chosen">
                    <span className="schema-row__name" title={name}>{name}</span>
                    <button type="button" className="schema-row__remove" aria-label={`Remove ${name}`} onClick={() => { onChange(selected.filter(item => item !== name)); setNote(""); }}>×</button>
                  </div>
                ))}
          </div>
        </div>
      </div>
    </section>
  );
}
