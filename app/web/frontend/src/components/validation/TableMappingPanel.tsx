import { useEffect, useMemo, useState } from "react";
import type { PlanResponse, SchemaMatch } from "../../api/types";
import { Badge } from "../ui/Badge";
import { ArrowRightIcon } from "../ui/icons";

interface Props {
  plan: PlanResponse;
  onChange: (map: Record<string, string>) => void;
}

export function TableMappingPanel({ plan, onChange }: Props) {
  const overrideKeys = useMemo(() => {
    const keys: string[] = [];
    for (const m of plan.schema_matches)
      for (const name of m.unmatched_source_tables) keys.push(`${m.source}.${name}`);
    return keys;
  }, [plan]);

  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setOverrides({});
    setOpen({});
  }, [overrideKeys]);

  useEffect(() => {
    const map: Record<string, string> = {};
    for (const [key, value] of Object.entries(overrides)) {
      const t = value.trim();
      if (t) map[key] = t;
    }
    onChange(map);
  }, [overrides, onChange]);

  if (!plan.schema_matches.length) {
    return <div className="empty">No matched schemas to expand.</div>;
  }

  return (
    <div>
      {plan.schema_matches.map((m) => (
        <SchemaBlock
          key={`${m.source}->${m.target}`}
          match={m}
          isOpen={!!open[m.source]}
          onToggle={() => setOpen((o) => ({ ...o, [m.source]: !o[m.source] }))}
          overrides={overrides}
          setOverride={(key, value) =>
            setOverrides((o) => ({ ...o, [key]: value }))
          }
        />
      ))}
    </div>
  );
}

function SchemaBlock({
  match,
  isOpen,
  onToggle,
  overrides,
  setOverride,
}: {
  match: SchemaMatch;
  isOpen: boolean;
  onToggle: () => void;
  overrides: Record<string, string>;
  setOverride: (key: string, value: string) => void;
}) {
  const counts =
    `${match.matched_tables.length} matched · ` +
    `${match.unmatched_source_tables.length} source-only · ` +
    `${match.unmatched_target_tables.length} target-only`;

  return (
    <div className="table-map-block">
      <button type="button" className="disclosure" onClick={onToggle}>
        <span>
          {match.source} <ArrowRightIcon size={13} /> {match.target}
        </span>
        <span className="disclosure__counts">{counts}</span>
      </button>
      {isOpen && (
        <div className="table-map-inner">
          {match.matched_tables.map((t) => (
            <div className="tmap-row" key={t.source}>
              <span className="tmap-src">{t.source}</span>
              <ArrowRightIcon size={13} className="tmap-arrow" />
              <span className="tmap-tgt">{t.target}</span>
              <Badge tone={t.match_type === "exact" ? "success" : "warning"}>
                {t.match_type}
              </Badge>
            </div>
          ))}
          {match.unmatched_source_tables.map((name) => {
            const key = `${match.source}.${name}`;
            return (
              <div className="tmap-row" key={key}>
                <span className="tmap-src">{name}</span>
                <ArrowRightIcon size={13} className="tmap-arrow" />
                <input
                  className="input input--sm"
                  placeholder="(skip)"
                  value={overrides[key] ?? ""}
                  onChange={(e) => setOverride(key, e.target.value)}
                />
                <Badge tone="danger">source-only</Badge>
              </div>
            );
          })}
          {match.unmatched_target_tables.length > 0 && (
            <div className="tmap-targets">
              <span className="muted-label">Target-only: </span>
              {match.unmatched_target_tables.map((n) => (
                <span key={n} className="chip-static">
                  {n}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
