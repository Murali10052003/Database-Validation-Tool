import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowRight, Check, ChevronDown, ChevronUp, X } from "lucide-react";
import type {
  ConnectionInput,
  MigrationRequest,
  PlanProgress,
  PlanResponse,
  TestConnectionResponse,
  ValidationProfileName,
  ValidationReport,
  ValidationCheck,
} from "../api/types";
import { api, ApiError } from "../api/client";
import { authorizeConnection, forgetAccount, initializeEntra, signedInAccount } from "../auth/entra";
import { SOURCE_DB_TYPES, TARGET_DB_TYPES } from "../data/dbTypes";
import { type SavedConnection } from "../data/savedConnections";
import { SavedConnectionsPanel } from "../components/validation/SavedConnectionsPanel";
import { connectionEngineNames, matchesConnection } from "../components/validation/savedConnectionModel";
import { Topbar } from "../components/layout/Topbar";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { ConnectionForm } from "../components/validation/ConnectionForm";
import { DiscoveryPanel } from "../components/validation/DiscoveryPanel";
import { DiscoveryProgress } from "../components/validation/DiscoveryProgress";
import { SchemaMappingPanel } from "../components/validation/SchemaMappingPanel";
import { SchemaScopePanel } from "../components/validation/SchemaScopePanel";
import { ObjectScopePanel } from "../components/validation/ObjectScopePanel";
import { InventoryBrowser } from "../components/validation/InventoryBrowser";
import { ProfileSelector } from "../components/validation/ProfileSelector";
import { metadataMode, parseObjects, planScope, presetChecks, schemaMapping, scopeReady, suggestTargetSchemas } from "../components/validation/validationSelection";
import { RunProgress } from "../components/validation/RunProgress";
import { ResultsPanel } from "../components/validation/ResultsPanel";
import { CheckIcon, PlayIcon } from "../components/ui/icons";
import { useToast } from "../state/ToastContext";
import { useActivity } from "../state/ActivityContext";
import { useSettings } from "../state/SettingsContext";
import { statusTone } from "../utils/format";
import "../styles/run-workflow.css";

export function RunValidationPage() {
  const { push } = useToast();
  const { log } = useActivity();
  const { settings } = useSettings();

  const [source, setSource] = useState<Partial<ConnectionInput>>({});
  const [target, setTarget] = useState<Partial<ConnectionInput>>({});
  const [sourceLoad, setSourceLoad] = useState<{ conn: SavedConnection; nonce: number } | null>(null);
  const [targetLoad, setTargetLoad] = useState<{ conn: SavedConnection; nonce: number } | null>(null);
  const [checks, setChecks] = useState<Partial<TestConnectionResponse>>({});
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const discoverySections = useRef<HTMLFieldSetElement>(null);
  const [loadedPlanVersion, setLoadedPlanVersion] = useState(0);

  useEffect(() => {
    if (loadedPlanVersion > 0) {
      discoverySections.current?.querySelectorAll("details").forEach(section => {
        section.open = true;
      });
    }
  }, [loadedPlanVersion]);
  const [schemaMap, setSchemaMap] = useState<Record<string, string>>({});
  const [tableMap, setTableMap] = useState<Record<string, string>>({});
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});
  const [typeOverrides, setTypeOverrides] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState<ValidationProfileName>(settings.validationMode);
  const [selectedChecks, setSelectedChecks] = useState<ValidationCheck[]>(() => presetChecks(settings.validationMode));
  const [name, setName] = useState("Ad-hoc migration");
  const [included, setIncluded] = useState("");
  const [excluded, setExcluded] = useState("");
  const [allObjects, setAllObjects] = useState(true);
  const [discoveryMode, setDiscoveryMode] = useState<"full" | "refresh" | "reuse">("full");
  const [mappingVersion, setMappingVersion] = useState<string | null>(null);
  const [sourceSchemas, setSourceSchemas] = useState<string[]>([]);
  const [targetSchemas, setTargetSchemas] = useState<string[]>([]);
  const [sourceAvailable, setSourceAvailable] = useState<string[] | null>(null);
  const [targetAvailable, setTargetAvailable] = useState<string[] | null>(null);
  const [step, setStep] = useState<"connections" | "discovery" | "review">("connections");
  const [savedToken, setSavedToken] = useState(0);
  const [resultsOpen, setResultsOpen] = useState(false);
  const resultsDialog = useRef<HTMLDialogElement>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

  const [busy, setBusy] = useState<null | "test-source" | "test-target" | "schemas-source" | "schemas-target" | "discover" | "validate">(null);
  const [progress, setProgress] = useState({ running: false, done: false, success: false });
  const [progressError, setProgressError] = useState("");
  const [discoveryProgress, setDiscoveryProgress] = useState<PlanProgress | null>(null);

  useEffect(() => {
    if (!runId || !progress.running) return;
    let active = true;
    let pending = false;
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const run = await api.getRun(runId);
        if (!active) return;
        if (run.state === "completed") {
          const data = await api.getReport(run.report_id || runId);
          if (!active) return;
          setReport(data);
          setProgress({ running: false, done: true, success: true });
          const level = data.overall_status === "PASS" ? "success" : data.overall_status === "FAIL" ? "error" : "warning";
          push(`Validation complete: ${data.overall_status}`, level === "warning" ? "info" : level);
          log(level, "validate", `${data.migration_name}: ${data.overall_status} (${data.summary.passed}/${data.summary.total} passed)`);
        } else if (["failed", "interrupted"].includes(run.state)) {
          setProgress({ running: false, done: true, success: false });
          push(`Validation ${run.state}. Saved results are available in Run logs.`, "error");
        }
        setProgressError("");
      } catch {
        if (active) setProgressError("Progress unavailable. Validation may still be running.");
      } finally { pending = false; }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, progress.running, push, log]);

  const clearPlan = useCallback(() => {
    setPlan(null);
    setSchemaMap({});
    setTableMap({});
    setColumnMap({});
    setTypeOverrides({});
    setIncluded("");
    setExcluded("");
    setAllObjects(true);
    setDiscoveryMode("full");
    setMappingVersion(null);
  }, []);
  const invalidate = useCallback(() => {
    clearPlan();
    setSourceSchemas([]);
    setTargetSchemas([]);
    setSourceAvailable(null);
    setTargetAvailable(null);
  }, [clearPlan]);
  const onSource = useCallback((connection: Partial<ConnectionInput>) => { setSource(connection); setChecks(current => ({...current, source: undefined})); invalidate(); }, [invalidate]);
  const onTarget = useCallback((connection: Partial<ConnectionInput>) => { setTarget(connection); setChecks(current => ({...current, target: undefined})); invalidate(); }, [invalidate]);
  useEffect(() => { void initializeEntra(); }, []);
  const onSchemaMap = useCallback((m: Record<string, string>) => setSchemaMap(m), []);
  useEffect(() => {
    if (resultsOpen && !resultsDialog.current?.open) resultsDialog.current?.showModal();
    if (!resultsOpen && resultsDialog.current?.open) resultsDialog.current.close();
  }, [resultsOpen]);

  const [sourceReset, setSourceReset] = useState(0);
  const [targetReset, setTargetReset] = useState(0);
  const clearSource = () => { setSourceLoad(null); setSourceReset(value => value + 1); onSource({}); };
  const clearTarget = () => { setTargetLoad(null); setTargetReset(value => value + 1); onTarget({}); };
  const loadNonce = useRef(0);
  const useAsSource = (conn: SavedConnection) => {
    setSourceLoad({ conn, nonce: ++loadNonce.current });
    push(`Loaded ${connectionEngineNames[conn.type]} into Source`, "success");
  };
  const useAsTarget = (conn: SavedConnection) => {
    setTargetLoad({ conn, nonce: ++loadNonce.current });
    push(`Loaded ${connectionEngineNames[conn.type]} into Target`, "success");
  };

  const basePayload = (): MigrationRequest => ({
    source,
    target,
    profile,
    discovery_mode: discoveryMode,
    source_inventory_id: plan?.source_inventory_id,
    target_inventory_id: plan?.target_inventory_id,
    mapping_version_id: mappingVersion,
    source_schemas: sourceSchemas.length ? sourceSchemas : undefined,
    target_schemas: targetSchemas.length ? targetSchemas : undefined,
  });

  const mappingPayload = () => ({schemas: schemaMap, tables: tableMap, columns: columnMap, type_overrides: typeOverrides, included_objects: allObjects ? [] : parseObjects(included), excluded_objects: parseObjects(excluded)});
  const loadPlan = (data: PlanResponse, payload?: MigrationRequest) => {
    setLoadedPlanVersion(version => version + 1);
    const mapping = payload?.mapping || data.saved_mapping;
    setPlan(data);
    setSchemaMap(schemaMapping(data, mapping?.schemas));
    setTableMap(mapping?.tables || {});
    setColumnMap(mapping?.columns || {});
    setTypeOverrides(mapping?.type_overrides || {});
    setIncluded((mapping?.included_objects || []).join(", "));
    setExcluded((mapping?.excluded_objects || []).join(", "));
    setAllObjects(!mapping?.included_objects?.length);
    setMappingVersion(payload?.mapping_version_id || data.mapping_version_id || null);
    const scope = planScope(data);
    setSourceSchemas(scope.source);
    setTargetSchemas(scope.target);
    setDiscoveryMode(metadataMode(data));
    if (payload?.selected_checks) { setSelectedChecks(payload.selected_checks); setProfile(payload.profile); }
    setStep("discovery");
  };

  async function run<T>(kind: "test-source" | "test-target" | "schemas-source" | "schemas-target" | "discover" | "validate", fn: () => Promise<T>) {
    setBusy(kind);
    try {
      return await fn();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      push(message, "error");
      log("error", "run", message);
      throw err;
    } finally {
      setBusy(null);
    }
  }

  const testConnection = (side: "source" | "target") =>
    run(`test-${side}`, async () => {
      const connection = side === "source" ? source : target;
      setChecks(current => ({ ...current, [side]: undefined }));
      if (!connection.host || !connection.username) throw new Error("Enter the database host and username before testing.");
      try {
        const authorized = await authorizeConnection(connection, true);
        const result = await api.testSingleConnection(authorized);
        setChecks(current => ({ ...current, [side]: result }));
        push(`${side === "source" ? "Source" : "Target"} connection test complete`, result.success ? "success" : "error");
        log(result.success ? "success" : "warning", "connect", `${side}: ${result.success ? "OK" : "FAIL"}`);
      } catch (error) {
        if (connection.type) setChecks(current => ({ ...current, [side]: {
          success: false, database_type: connection.type!, error: error instanceof Error ? error.message : "Connection test failed.",
        } }));
        throw error;
      }
    }).catch(() => {});

  const disconnectAccount = (side: "source" | "target") => {
    forgetAccount(side === "source" ? source : target);
    setChecks(current => ({ ...current, [side]: undefined }));
    invalidate();
  };

  const loadSchemas = (side: "source" | "target") =>
    run(`schemas-${side}`, async () => {
      const connection = side === "source" ? source : target;
      if (!connection.host || !connection.username) throw new Error("Enter the database host and username before loading schemas.");
      const result = await api.listSchemas(await authorizeConnection(connection));
      (side === "source" ? setSourceAvailable : setTargetAvailable)(result.schemas);
      push(`${result.schemas.length} ${side} schemas available`, "success");
      log("success", "discover", `${side}: ${result.schemas.length} schemas listed`);
    }).catch(() => {});

  const changeScope = (side: "source" | "target", selected: string[]) => {
    (side === "source" ? setSourceSchemas : setTargetSchemas)(selected);
    clearPlan();
  };

  const discover = () =>
    run("discover", async () => {
      if (!scopeReady(sourceSchemas, targetSchemas)) throw new Error("Select at least one source schema and one target schema before Discover & match.");
      const progressId = crypto.randomUUID().replace(/-/g, "");
      let active = true;
      setDiscoveryProgress({ state: "running", percent: 0, stage: "Starting discovery" });
      const timer = window.setInterval(() => {
        api.planProgress(progressId).then(snapshot => { if (active && snapshot.state === "running") setDiscoveryProgress(snapshot); }).catch(() => {});
      }, 700);
      try {
        const data = await api.plan({ ...basePayload(), mapping: {} }, progressId);
        loadPlan(data);
        push("Discovery complete — review the auto-matched mapping", "success");
        log("success", "discover", `${data.source.tables} source · ${data.target.tables} target tables · ${data.schema_matches.length} schema matches`);
      } finally {
        active = false;
        window.clearInterval(timer);
        setDiscoveryProgress(null);
      }
    }).catch(() => {});

  const validate = () =>
    run("validate", async () => {
      setProgress({ running: true, done: false, success: false });
      setResultsOpen(true);
      setReport(null);
      setProgressError("");
      const executionId = crypto.randomUUID().replace(/-/g, "");
      setRunId(null);
      const includedList = allObjects ? [] : parseObjects(included);
      const excludedList = parseObjects(excluded);
      try {
        const accepted = await api.submitValidation({
          name: name.trim() || "Ad-hoc migration",
          ...basePayload(),
          selected_checks: selectedChecks,
          mapping: { ...mappingPayload(), tables: Object.fromEntries(Object.entries(tableMap).map(([key, value]) => [key, value.trim()])), included_objects: includedList, excluded_objects: excludedList },
        }, executionId);
        setRunId(accepted.run_id);
        push("Background validation accepted", "success");
        log("info", "validate", `Validation submitted: ${accepted.run_id}`);
      } catch (err) {
        setRunId(executionId);
        setProgress({ running: false, done: true, success: false });
        setProgressError("Submission was not confirmed. Check Run logs before retrying.");
        throw err;
      }
    }).catch(() => {});

  const connected = !!checks.source?.success && !!checks.target?.success;
  const canDiscover = connected && scopeReady(sourceSchemas, targetSchemas);
  const hasObjects = allObjects || parseObjects(included).length > 0;
  const hasMappedSchemas = Object.values(schemaMap).some(target => target.trim());
  const canValidate = connected && !!plan && hasMappedSchemas && hasObjects && selectedChecks.length > 0 && !busy && !progress.running;
  const describeConnection = (connection: Partial<ConnectionInput>) => connection.host ? `${connection.type ? connectionEngineNames[connection.type] : ""} / ${connection.database || connection.service || connection.host}` : "Not configured";
  const excludedCount = parseObjects(excluded).length;
  const scopeSummary = allObjects
    ? (excludedCount ? `All objects except ${excludedCount}` : "All objects")
    : `${parseObjects(included).length} included objects${excludedCount ? `, ${excludedCount} excluded` : ""}`;
  const schemaScopeLabel = (names: string[]) => names.length ? names.join(", ") : "Not selected";

  return (
    <>
      <Topbar title="Run validation" subtitle="Connect · discover · review · validate" />
      <div className="run-validation run-workflow">
        <div className="workflow-steps">
          <WorkflowStep id="connections" number={1} title="Connections" summary={`${describeConnection(source)} to ${describeConnection(target)}`} open={step === "connections"} complete={connected} onOpen={() => setStep("connections")}>
            <fieldset disabled={!!busy} className="workflow-fields">
              <SavedConnectionsPanel compact revealToken={savedToken} source={source} target={target} onSource={useAsSource} onTarget={useAsTarget} onDelete={connection => {
                if (matchesConnection(connection, source)) clearSource();
                if (matchesConnection(connection, target)) clearTarget();
              }} />
              <div className="grid-2 connection-editors">
                <ConnectionForm key={`source-${sourceReset}`} title="Source" dbTypes={SOURCE_DB_TYPES} check={checks.source ?? null} onChange={onSource} load={sourceLoad} onSaved={() => setSavedToken(value => value + 1)} onTest={() => testConnection("source")} testing={busy === "test-source"} signedInAs={signedInAccount(source)} onDisconnect={() => disconnectAccount("source")} />
                <ConnectionForm key={`target-${targetReset}`} title="Target" dbTypes={TARGET_DB_TYPES} check={checks.target ?? null} onChange={onTarget} load={targetLoad} onSaved={() => setSavedToken(value => value + 1)} onTest={() => testConnection("target")} testing={busy === "test-target"} signedInAs={signedInAccount(target)} onDisconnect={() => disconnectAccount("target")} />
              </div>
            </fieldset>
          </WorkflowStep>
          <WorkflowStep id="discovery" number={2} title="Discovery & Object Scope" summary={plan ? `${plan.source.tables} source tables / ${schemaScopeLabel(sourceSchemas)} / ${scopeSummary}` : "Pending discovery"} open={step === "discovery"} complete={!!plan && hasObjects} onOpen={() => setStep("discovery")}>
            <fieldset ref={discoverySections} disabled={!!busy} className="workflow-fields">
              <div className="workflow-section-heading"><h3>Schema scope</h3></div>
              <p className="field__hint">Choose the schemas to discover on each side. Only these schemas are read; unrelated schemas are never scanned.</p>
              <div className="schema-scope-grid">
                <SchemaScopePanel label="Source" engine={source.type} available={sourceAvailable} selected={sourceSchemas} onChange={selected => changeScope("source", selected)} action={<Button variant="secondary" disabled={!checks.source?.success || !!busy} loading={busy === "schemas-source"} onClick={() => void loadSchemas("source")}>Load schemas</Button>} />
                <SchemaScopePanel label="Target" engine={target.type} available={targetAvailable} selected={targetSchemas} suggested={suggestTargetSchemas(sourceSchemas, targetAvailable, targetSchemas)} onChange={selected => changeScope("target", selected)} action={<Button variant="secondary" disabled={!checks.target?.success || !!busy} loading={busy === "schemas-target"} onClick={() => void loadSchemas("target")}>Load schemas</Button>} />
              </div>
              <div className="workflow-section-heading"><h3>Discovery</h3><Button variant="secondary" icon={<CheckIcon size={16} />} disabled={!canDiscover || !!busy} loading={busy === "discover"} onClick={discover}>{plan ? "Rediscover" : "Discover & match"}</Button></div>
              {busy === "discover" && discoveryProgress && <DiscoveryProgress progress={discoveryProgress} />}
              <InventoryBrowser key={`${source.host}-${source.database}-${source.service}-${source.username}-${target.host}-${target.database}-${target.username}`} request={{...basePayload(), mapping: mappingPayload()}} onLoad={loadPlan} />
              {plan && <label className="field"><span className="field__label">Metadata mode</span><select className="input" value={discoveryMode} onChange={event => setDiscoveryMode(event.target.value as typeof discoveryMode)}><option value="refresh" disabled={plan.metadata_complete === false}>Refresh selected objects</option><option value="reuse" disabled={plan.metadata_complete === false}>Reuse saved metadata</option><option value="full">Full discovery</option></select></label>}
              {plan?.metadata_complete === false && <p className="field__hint">Discovery read schema and table names only. Columns, constraints, indexes and other objects are collected when validation runs, limited to the schemas selected above.</p>}
              {discoveryMode === "reuse" && <p role="alert">Saved metadata may be stale. Schema changes made after discovery will not be detected.</p>}
              {!connected && <p className="workflow-empty">Connections have not passed testing.</p>}
              {connected && !plan && <p className="workflow-empty">{canDiscover ? "Discovery has not run." : "Select at least one source schema and one target schema to enable discovery."}</p>}
              {plan && <>
                <details className="workflow-details"><summary>Discovery summary</summary><DiscoveryPanel plan={plan} /></details>
                <details className="workflow-details"><summary>Schema mapping</summary><SchemaMappingPanel plan={plan} value={schemaMap} onChange={onSchemaMap} /></details>
                <Button variant="secondary" onClick={() => void run("discover", async () => {
                  const payload = {...basePayload(), mapping: mappingPayload()};
                  const saved = await api.saveMapping(payload);
                  const updated = await api.inventoryPlan(payload);
                  setPlan(updated); setMappingVersion(saved.id);
                  push("Mapping and scope saved", "success");
                }).catch(() => {})}>Save mapping and scope</Button>
                <ObjectScopePanel plan={plan} all={allObjects} included={included} excluded={excluded} schemas={schemaMap} tables={tableMap} onScope={(all, value) => { setAllObjects(all); setIncluded(value); }} onExcluded={setExcluded} onTables={setTableMap} />
              </>}
            </fieldset>
          </WorkflowStep>
          <WorkflowStep id="review" number={3} title="Review & Validate" summary={`${profile} / ${selectedChecks.length} checks`} open={step === "review"} complete={!!report} onOpen={() => setStep("review")}>
            <fieldset disabled={!!busy} className="workflow-fields">
              <ProfileSelector value={profile} selected={selectedChecks} onChange={(value, selection) => { setProfile(value); setSelectedChecks(selection); }} />
              <section className="workflow-review"><h3>Run summary</h3>
                <label className="field"><span className="field__label">Migration name</span><input className="input" value={name} onChange={event => setName(event.target.value)} /></label>
                <dl><div><dt>Source</dt><dd>{describeConnection(source)}</dd></div><div><dt>Target</dt><dd>{describeConnection(target)}</dd></div><div><dt>Source schemas</dt><dd>{schemaScopeLabel(sourceSchemas)}</dd></div><div><dt>Target schemas</dt><dd>{schemaScopeLabel(targetSchemas)}</dd></div><div><dt>Included</dt><dd>{allObjects ? "All objects" : included || "None"}</dd></div><div><dt>Excluded</dt><dd>{excluded || "None"}</dd></div><div><dt>Connection test</dt><dd>{connected ? "Passed" : "Required"}</dd></div><div><dt>Discovery</dt><dd>{plan ? "Complete" : "Required"}</dd></div></dl>
              </section>
            </fieldset>
          </WorkflowStep>
        </div>
        <footer className="workflow-actionbar">
          <div className="workflow-actionbar__summary"><strong>{selectedChecks.length} checks selected</strong><span>{scopeSummary}{busy ? ` / ${busy.startsWith("test-") ? "Testing connection" : busy.startsWith("schemas-") ? "Loading schemas" : busy === "discover" ? `Discovering objects${discoveryProgress?.percent != null ? ` ${Math.round(discoveryProgress.percent)}%` : ""}` : "Validation running"}` : ""}</span></div>
          <div className="workflow-actionbar__buttons">
            {(progress.running || progress.done) && <Button variant="secondary" onClick={() => setResultsOpen(true)}>{progress.running ? "View progress" : "View last run"}</Button>}
            {step === "connections" && <Button variant="secondary" icon={<ArrowRight size={16} />} disabled={!!busy || !connected} onClick={() => setStep("discovery")}>Continue to discovery</Button>}
            {step === "discovery" && <Button variant="secondary" icon={plan ? <ArrowRight size={16} /> : <CheckIcon size={16} />} loading={busy === "discover"} disabled={!!busy || !connected || (!plan && !canDiscover) || (!!plan && !hasObjects)} onClick={plan ? () => setStep("review") : discover}>{plan ? "Review selection" : "Discover & match"}</Button>}
            <Button variant="primary" icon={<PlayIcon size={16} />} loading={busy === "validate"} disabled={!canValidate} onClick={validate}>Run validation</Button>
          </div>
        </footer>
      </div>
      <dialog ref={resultsDialog} className="workflow-results" aria-labelledby="workflow-results-title" onCancel={() => setResultsOpen(false)} onClose={() => setResultsOpen(false)}>
        <header><h2 id="workflow-results-title">{progress.running ? "Validation in progress" : "Validation results"}</h2><button type="button" className="connections-icon" aria-label="Close results" title="Close results" onClick={() => setResultsOpen(false)}><X size={18} /></button></header>
        <RunProgress running={progress.running} done={progress.done} success={progress.success} runId={runId} outcome={report?.overall_status} />
        {progressError && <p role="status">{progressError}</p>}
        {report && <Card title="Results" actions={<Badge tone={statusTone(report.overall_status)}>OVERALL: {report.overall_status}</Badge>}><ResultsPanel report={report} /></Card>}
      </dialog>
    </>
  );
}

function WorkflowStep({ id, number, title, summary, open, complete, onOpen, children }: { id: string; number: number; title: string; summary: string; open: boolean; complete: boolean; onOpen: () => void; children: ReactNode }) {
  return <section className={`workflow-step${open ? " is-open" : ""}`}>
    <h2><button className="workflow-step__toggle" id={`step-${id}`} type="button" aria-expanded={open} aria-controls={`body-${id}`} onClick={onOpen}>
      <span className={`workflow-step__number${complete ? " is-complete" : ""}`}>{complete ? <Check size={16} /> : number}</span><span className="workflow-step__title">{title}<small>{summary}</small></span>{open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
    </button></h2>
    <div className="workflow-step__body" id={`body-${id}`} role="region" aria-labelledby={`step-${id}`} hidden={!open}>{children}</div>
  </section>;
}
