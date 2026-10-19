import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { PartialRunReport, RunEvent, RunRecord } from "../api/types";
import { Topbar } from "../components/layout/Topbar";
import { RefreshIcon } from "../components/ui/icons";

export function RunLogsPage() {
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") || "";
  const query = params.get("query") || "";
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [selected, setSelected] = useState<RunRecord | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [level, setLevel] = useState("");
  const [stage, setStage] = useState("");
  const [offset, setOffset] = useState(0);
  const [runOffset, setRunOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [listLoading, setListLoading] = useState(true);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setListLoading(true);
    api.listRuns(runOffset).then((data) => { if (active) { setRuns(data); setListError(""); } })
      .catch((err) => { if (active) setListError(String(err)); })
      .finally(() => { if (active) setListLoading(false); });
    return () => { active = false; };
  }, [revision, runOffset]);

  useEffect(() => { setOffset(0); }, [runId, query, level, stage]);
  useEffect(() => {
    let active = true;
    let inFlight = false;
    setEvents([]); setSelected(null); setTotal(0); setError("");
    if (!runId) return;
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      setLoading(true);
      try {
        const [run, data] = await Promise.all([api.getRun(runId), api.runEvents(runId, {
          level, stage, query, offset: String(offset), limit: "100",
        })]);
        if (active) { setSelected(run); setEvents(data.items); setTotal(data.total); setError(""); }
      } catch (err) { if (active) setError(String(err)); }
      finally { inFlight = false; if (active) setLoading(false); }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, level, stage, query, offset, revision]);

  return <>
    <Topbar title="Run logs" subtitle="Persistent execution history" />
    <div className="page run-logs">
      <div className="logs-toolbar">
        <select className="input" aria-label="Select run" value={runId} onChange={(event) => setParams({ run: event.target.value })}>
          <option value="">Select a run</option>
          {runId && !runs.some((run) => run.id === runId) && <option value={runId}>{runId}</option>}
          {runs.map((run) => <option key={run.id} value={run.id}>{run.started_at} | {run.name} | {run.state} {run.outcome || ""}</option>)}
        </select>
        <button className="btn btn--ghost" title="Refresh runs and events" aria-label="Refresh runs and events" onClick={() => setRevision((value) => value + 1)}><RefreshIcon /></button>
      </div>
      <div className="vr-check-links">
        <button className="btn btn--ghost btn--sm" disabled={!runOffset} onClick={() => setRunOffset(Math.max(0, runOffset - 100))}>Newer runs</button>
        <button className="btn btn--ghost btn--sm" disabled={runs.length < 100} onClick={() => setRunOffset(runOffset + 100)}>Older runs</button>
      </div>
      {listError && <p role="alert">{listError}</p>}
      {listLoading && <p role="status">Loading run history</p>}
      {selected && <div className="run-summary">
        <strong>{selected.name}</strong>
        <p>Execution: {selected.state} | Validation: {selected.outcome || "No result"} | Profile: {selected.profile}</p>
        <p>{selected.started_at} to {selected.finished_at || "Completion not recorded"}</p>
        <div className="vr-check-links">
          <a className="btn btn--ghost btn--sm" href={api.runLogUrl(runId)}>Download sanitized logs</a>
          {selected.report_id && <Link to={`/reports/${selected.report_id}`}>Open report</Link>}
        </div>
      </div>}
      {runId && <>
        <SavedResults key={runId} runId={runId} revision={revision} />
        <div className="logs-toolbar">
          <select className="input" aria-label="Log level" value={level} onChange={(event) => setLevel(event.target.value)}>
            <option value="">All levels</option>{["info", "warning", "error"].map((value) => <option key={value}>{value}</option>)}
          </select>
          <input className="input" aria-label="Log stage" placeholder="Stage" value={stage} onChange={(event) => setStage(event.target.value)} />
          <input className="input" aria-label="Search run events" placeholder="Check, object or event" value={query} onChange={(event) => setParams({ run: runId, query: event.target.value })} />
        </div>
        {error ? <p role="alert">{error}</p> : <>
          <p aria-live="polite">{loading ? "Loading events" : `${total} matching events`}</p>
          <ol className="run-events">{events.map((event) => <li key={event.id} className={`run-event run-event--${event.level}`}>
            <div><time>{new Date(event.time).toLocaleString()}</time> <strong>{event.level.toUpperCase()}</strong> <span>{event.stage}</span></div>
            <div>{event.event.replace(/_/g, " ")}</div>
            <dl className="vr-coverage-grid">{Object.entries(event.details).filter(([, value]) => value != null).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, " ")}</dt><dd>{String(value)}</dd></div>)}</dl>
          </li>)}</ol>
          {!loading && !events.length && <p>No matching events.</p>}
          <div className="vr-check-links">
            <button className="btn btn--ghost btn--sm" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous events</button>
            <span>{total ? `${offset + 1}-${Math.min(offset + events.length, total)} of ${total}` : "0 events"}</span>
            <button className="btn btn--ghost btn--sm" disabled={offset + events.length >= total} onClick={() => setOffset(offset + 100)}>Next events</button>
          </div>
        </>}
      </>}
      {!runId && !listLoading && !listError && <p>{runs.length ? "No run selected." : "No persisted runs on this page."}</p>}
    </div>
  </>;
}

function SavedResults({ runId, revision }: { runId: string; revision: number }) {
  const [report, setReport] = useState<PartialRunReport | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let pending = false;
    setReport(null);
    setError("");
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const data = await api.runResults(runId, offset);
        if (active) { setReport(data); setError(""); }
      } catch (err) { if (active) setError(String(err)); }
      finally { pending = false; }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, offset, revision]);

  return <section aria-label="Saved check results">
    <h2>Saved check results</h2>
    {error ? <p role="alert">Saved results unavailable: {error}</p> : !report ? <p role="status">Loading saved results</p> : <>
      <p>Execution: {report.state} | {report.total} saved checks</p>
      {!report.coverage_complete && <p role="status"><strong>Incomplete validation. Saved checks are not an overall validation result.</strong></p>}
      {report.error && <p>Execution error: {report.error}</p>}
      <p>{Object.entries(report.counts).map(([status, count]) => `${status}: ${count}`).join(" | ") || "No completed checks saved."}</p>
      <dl className="vr-coverage-grid">{report.stages.map(({ stage, status }) => <div key={stage}><dt>{stage.replace(/_/g, " ")}</dt><dd>{status}</dd></div>)}</dl>
      <ol className="run-events">{report.results.map((result) => <li key={JSON.stringify([result.check_id, result.category, result.source_object, result.target_object])} className="run-event">
        <div><strong>{result.status}</strong> {result.check_id}</div>
        <div>{result.source_object || "Source not specified"} to {result.target_object || "Target not specified"}</div>
        {result.message && <p>{result.message}</p>}
        <details><summary>Check evidence</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(result, null, 2)}</pre></details>
      </li>)}</ol>
      <div className="vr-check-links">
        <button className="btn btn--ghost btn--sm" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous checks</button>
        <span>{report.total ? `${Math.min(offset + 1, report.total)}-${Math.min(offset + report.results.length, report.total)} of ${report.total}` : "0 checks"}</span>
        <button className="btn btn--ghost btn--sm" disabled={offset + report.results.length >= report.total} onClick={() => setOffset(offset + 100)}>Next checks</button>
      </div>
    </>}
  </section>;
}