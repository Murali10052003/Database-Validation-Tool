import { useState } from "react";
import { Archive, RefreshCw, RotateCcw, Save } from "lucide-react";
import { api } from "../../api/client";
import type { MigrationRequest, PlanResponse } from "../../api/types";
import { useToast } from "../../state/ToastContext";

type SearchResult = Awaited<ReturnType<typeof api.inventorySearch>>;

export function InventoryBrowser({ request, onLoad }: {request: MigrationRequest; onLoad: (plan: PlanResponse, request: MigrationRequest) => void}) {
  const [data, setData] = useState<SearchResult | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [mappingId, setMappingId] = useState("");
  const [busy, setBusy] = useState(false);
  const { push } = useToast();
  async function action(work: () => Promise<void>) {
    setBusy(true);
    try { await work(); } catch (reason) { push(String(reason), "error"); }
    finally { setBusy(false); }
  }
  async function load(payload: MigrationRequest) {
    const plan = await api.inventoryPlan(payload);
    onLoad(plan, payload);
    push("Saved inventory loaded; no database discovery was run", "success");
  }
  return <details className="workflow-details">
    <summary>Saved inventories and previous runs</summary>
    <fieldset disabled={busy} className="workflow-fields">
      <div className="scope-actions">
        <button className="btn btn--secondary btn--sm" type="button" onClick={() => void action(async () => {
          const found = await api.inventorySearch(request); setData(found);
          setSourceId(found.source[0]?.id || ""); setTargetId(found.target[0]?.id || ""); setMappingId(found.mappings[0]?.id || "");
        })}><RefreshCw size={15} />Find saved inventories</button>
        <button className="btn btn--secondary btn--sm" type="button" onClick={() => void action(async () => { const result = await api.backupCatalog(); push(`Catalog backup created: ${result.filename}`, "success"); })}><Save size={15} />Back up catalog</button>
      </div>
      {data && <>
        <div className="scope-fields">
          <label className="field"><span className="field__label">Source inventory</span><select className="input" value={sourceId} onChange={event => setSourceId(event.target.value)}><option value="">Select inventory</option>          {data.source.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} / {item.id.slice(0, 8)}{item.metadata_complete === false ? " / names only" : ""}</option>)}</select></label>
                    <label className="field"><span className="field__label">Target inventory</span><select className="input" value={targetId} onChange={event => setTargetId(event.target.value)}><option value="">Select inventory</option>{data.target.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} / {item.id.slice(0, 8)}{item.metadata_complete === false ? " / names only" : ""}</option>)}</select></label>
          <label className="field"><span className="field__label">Mapping version</span><select className="input" value={mappingId} onChange={event => setMappingId(event.target.value)}><option value="">Current mapping</option>{data.mappings.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} / {item.id.slice(0, 8)}</option>)}</select></label>
        </div>
        <button className="btn btn--secondary btn--sm" type="button" disabled={!sourceId || !targetId} onClick={() => void action(async () => {
          const mapping = data.mappings.find(item => item.id === mappingId);
          await load({...request, source_inventory_id: sourceId, target_inventory_id: targetId, mapping_version_id: mapping?.id, mapping: mapping?.payload || request.mapping, discovery_mode: "refresh"});
        })}><Archive size={15} />Load selected inventory</button>
        {!data.source.length || !data.target.length ? <p>No saved inventory for one or both connections.</p> : null}
        {data.runs.map(run => <div className="workflow-section-heading" key={run.id}>
          <span>{run.report?.migration_name || run.id.slice(0, 12)} / {run.status} / {new Date(run.created_at).toLocaleString()}</span>
          <div className="scope-actions">{([false, true] as const).map(failedOnly => <button key={String(failedOnly)} className="btn btn--secondary btn--sm" type="button" disabled={!run.configuration.source_inventory_id || !run.configuration.target_inventory_id} onClick={() => void action(async () => {
            let included = run.configuration.mapping.included_objects || [];
            if (failedOnly) {
              included = [...new Set((run.report?.results || []).filter(result => ["FAIL", "ERROR"].includes(result.status)).map(result => result.source_object?.split(".").slice(0, 2).join(".")).filter((name): name is string => !!name))];
              if (!included.length) throw new Error("No source objects can be inferred from these failures. Use selected-object rerun.");
            }
            await load({...request, source_inventory_id: run.configuration.source_inventory_id, target_inventory_id: run.configuration.target_inventory_id, profile: run.configuration.validation.profile, selected_checks: run.configuration.validation.selected_checks, mapping: {...run.configuration.mapping, included_objects: included}, discovery_mode: "refresh"});
          })}><RotateCcw size={15} />{failedOnly ? "Rerun failed objects" : "Rerun selected objects"}</button>)}</div>
        </div>)}
      </>}
    </fieldset>
  </details>;
}