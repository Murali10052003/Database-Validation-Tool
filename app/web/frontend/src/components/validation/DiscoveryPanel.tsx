import type { ObjectCounts, PlanResponse } from "../../api/types";

const METRICS: [keyof ObjectCounts, string][] = [
  ["schemas", "Schemas"],
  ["tables", "Tables"],
  ["columns", "Columns"],
  ["indexes", "Indexes"],
  ["constraints", "Constraints"],
  ["sequences", "Sequences"],
  ["views", "Views"],
];

function Side({ label, counts, namesOnly }: { label: string; counts: ObjectCounts; namesOnly: boolean }) {
  return (
    <div className="disc-card">
      <h3>
        {label} · {counts.database_type} <span>({counts.version || "n/a"})</span>
      </h3>
      <div className="disc-tiles">
        {METRICS.filter(([key]) => !namesOnly || NAME_METRICS.has(key)).map(([key, name]) => (
          <div key={name} className="disc-tile">
            <div className="disc-tile__n">{Number(counts[key] ?? 0)}</div>
            <div className="disc-tile__l">{name}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

const NAME_METRICS = new Set<keyof ObjectCounts>(["schemas", "tables"]);

export function DiscoveryPanel({ plan }: { plan: PlanResponse }) {
  const namesOnly = plan.metadata_complete === false;
  return (
    <>
      <div className="discovery-grid">
        <Side label="Source" counts={plan.source} namesOnly={namesOnly} />
        <Side label="Target" counts={plan.target} namesOnly={namesOnly} />
      </div>
      {namesOnly && <p className="field__hint">Columns, constraints, indexes, sequences and views are not counted yet; they are collected when validation runs.</p>}
    </>
  );
}
