import { useEffect, useMemo, useState } from "react";
import type { PlanResponse } from "../../api/types";
import { Badge } from "../ui/Badge";
import { schemaMatchType } from "./validationSelection";

interface Row {
  source: string;
  target: string;
  matchType: string;
  candidates?: string[];
}

function toneFor(type: string): "success" | "warning" | "danger" | "muted" {
  if (type === "exact") return "success";
  if (type === "case_insensitive") return "warning";
  if (type === "unmatched") return "danger";
  return "muted";
}

function buildRows(plan: PlanResponse): Row[] {
  const rows: Row[] = [];
  for (const m of plan.schema_matches)
    rows.push({ source: m.source, target: m.target, matchType: m.match_type });
  for (const a of plan.ambiguous_schemas)
    rows.push({
      source: a.source,
      target: "",
      matchType: "ambiguous",
      candidates: a.candidates,
    });
  for (const s of plan.unmatched_source_schemas)
    rows.push({ source: s, target: "", matchType: "unmatched" });
  return rows;
}

interface Props {
  plan: PlanResponse;
  value?: Record<string, string>;
  onChange: (map: Record<string, string>) => void;
}

export function SchemaMappingPanel({ plan, value, onChange }: Props) {
  const initial = useMemo(() => buildRows(plan), [plan]);
  const [rows, setRows] = useState<Row[]>(initial);

  useEffect(() => setRows(initial), [initial]);

  useEffect(() => {
    const map: Record<string, string> = {};
    for (const r of rows) {
      const t = r.target.trim();
      map[r.source] = t;
    }
    if (value === undefined) onChange(map);
  }, [rows, onChange, value]);

  const setTarget = (index: number, target: string) => {
    if (value !== undefined) onChange({ ...value, [rows[index].source]: target });
    else setRows((list) => list.map((r, i) => (i === index ? { ...r, target } : r)));
  };

  const targets = [...new Set([
    ...plan.schema_matches.filter(match => match.match_type !== "unmatched").map(match => match.target),
    ...plan.unmatched_target_schemas,
    ...plan.ambiguous_schemas.flatMap(match => match.candidates),
  ])];

  return (
    <div>
      <div className="map-head">
        <span>Source schema</span>
        <span>Target schema</span>
        <span>Match</span>
      </div>
      {rows.map((r, i) => {
        const target = value === undefined ? r.target : value[r.source] ?? "";
        const matchType = schemaMatchType(r.source, target, targets);
        return (
        <div className="map-row" key={`${r.source}-${i}`}>
          <span className="map-source">{r.source}</span>
          {r.candidates ? (
            <select
              className="input select"
              value={target}
              aria-label={`Target schema for ${r.source}`}
              onChange={(e) => setTarget(i, e.target.value)}
            >
              <option value="">— choose —</option>
              {r.candidates.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="input"
              value={target}
              aria-label={`Target schema for ${r.source}`}
              placeholder="(skip)"
              onChange={(e) => setTarget(i, e.target.value)}
            />
          )}
          <Badge tone={toneFor(matchType)}>{matchType.replace("_", " ")}</Badge>
        </div>
      ); })}

      {plan.unmatched_target_schemas.length > 0 && (
        <div className="unmatched-target">
          <span className="muted-label">Target-only schemas (no source match):</span>
          <div className="chips">
            {plan.unmatched_target_schemas.map((n) => (
              <span key={n} className="chip-static">
                {n}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
