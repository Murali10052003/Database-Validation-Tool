import { useEffect, useState } from "react";
import { Check, Circle, CircleAlert, LoaderCircle, ScrollText } from "lucide-react";
import { api } from "../../api/client";
import type { RunEvent } from "../../api/types";
import { visibleRunStages } from "./runProgressModel";
import "../../styles/run-progress.css";

export function RunProgress({ runId, running, done, success, outcome }: {
  runId: string | null; running: boolean; done: boolean; success: boolean; outcome?: string;
}) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let pending = false;
    setEvents([]); setError("");
    if (!runId) return;
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const data = await api.runEvents(runId, { query: "stage_", limit: "500" });
        if (active) { setEvents(data.items); setError(""); }
      } catch { if (active) setError("Stage updates unavailable"); }
      finally { pending = false; }
    };
    void load();
    const timer = running ? window.setInterval(() => { void load(); }, 1500) : undefined;
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [runId, running]);
  const stages = visibleRunStages(events);
  const finishedCount = stages.filter(stage => events.some(event => event.stage === stage && event.event === "stage_finished")).length;
  const ExecutionIcon = running ? LoaderCircle : done ? success ? Check : CircleAlert : Circle;
  return <div className="run-progress">
    <div className="run-progress__header">
      <div className="run-progress__summary" role="status">
        <span className={`run-progress__execution run-progress__execution--${running ? "running" : done ? success ? "finished" : "error" : "idle"}`}><ExecutionIcon size={20} aria-hidden="true" className={running ? "run-progress__spin" : undefined} /></span>
        <div><strong>{running ? "Validation in progress" : done ? success ? "Execution complete" : "Execution failed" : "Ready to validate"}</strong>
          <p>{stages.length ? `${finishedCount} of ${stages.length} recorded stages finished` : running ? "Waiting for stage updates" : done ? "No stage updates recorded" : "Not started"}</p>
        </div>
      </div>
      {done && success && <span className={`run-progress__outcome run-progress__outcome--${(outcome || "unknown").toLowerCase()}`}>Validation: {outcome || "Unknown"}</span>}
      {runId && <a className="run-progress__logs" href={`#/logs?run=${encodeURIComponent(runId)}`}><ScrollText size={16} aria-hidden="true" />Run logs</a>}
    </div>
    {error && <p className="run-progress__warning" role="status"><CircleAlert size={16} aria-hidden="true" />{error}</p>}
    {!!stages.length && <ul className="run-progress__stages" aria-label="Validation stages">{stages.map((stage) => {
      const finished = events.find((event) => event.stage === stage && event.event === "stage_finished");
      const state = finished ? finished.details.status === "ERROR" ? "error" : "finished" : running ? "running" : "unknown";
      const StageIcon = state === "finished" ? Check : state === "error" ? CircleAlert : state === "running" ? LoaderCircle : Circle;
      const label = stage.split("_").map(word => word === "null" ? "NULL" : word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
      return <li key={stage} className={`run-progress__stage run-progress__stage--${state}`}>
        <span className="run-progress__stage-icon"><StageIcon size={17} aria-hidden="true" className={state === "running" ? "run-progress__spin" : undefined} /></span>
        <div><span className="run-progress__stage-name">{label}</span><span className="run-progress__stage-state">{state === "finished" ? "Finished" : state === "error" ? "Execution error" : state === "running" ? "Running" : "Completion not recorded"}</span></div>
      </li>;
    })}</ul>}
  </div>;
}