import { useMemo, useState } from "react";
import { Topbar } from "../components/layout/Topbar";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { useActivity, type ActivityLevel } from "../state/ActivityContext";
import { RunLogsPage } from "./RunLogsPage";

const LEVELS: (ActivityLevel | "all")[] = ["all", "info", "success", "warning", "error"];

export function LogsPage() {
  const [view, setView] = useState("runs");
  return <>
    <div className="logs-mode" role="group" aria-label="Log source">
      <button className="btn btn--ghost" aria-pressed={view === "runs"} onClick={() => setView("runs")}>Run logs</button>
      <button className="btn btn--ghost" aria-pressed={view === "browser"} onClick={() => setView("browser")}>Browser activity</button>
    </div>
    {view === "runs" ? <RunLogsPage /> : <BrowserActivity />}
  </>;
}

function BrowserActivity() {
  const { entries, clear } = useActivity();
  const [level, setLevel] = useState<ActivityLevel | "all">("all");
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter(
      (e) =>
        (level === "all" || e.level === level) &&
        (!q || e.message.toLowerCase().includes(q) || e.source.toLowerCase().includes(q)),
    );
  }, [entries, level, query]);

  return (
    <>
      <Topbar title="Logs" subtitle="Activity recorded during this session" />
      <div className="page">
        <Card
          title={`Activity (${entries.length})`}
          actions={
            <Button size="sm" variant="ghost" onClick={clear} disabled={!entries.length}>
              Clear
            </Button>
          }
        >
          <div className="logs-toolbar">
            <div className="filters">
              {LEVELS.map((l) => (
                <button
                  key={l}
                  className={`chip ${level === l ? "chip--active" : ""}`}
                  onClick={() => setLevel(l)}
                >
                  {l.toUpperCase()}
                </button>
              ))}
            </div>
            <input
              className="input search"
              placeholder="Filter logs…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {rows.length === 0 ? (
            <div className="empty">No log entries.</div>
          ) : (
            <div className="log-list">
              {rows.map((e) => (
                <div key={e.id} className={`log-row log-row--${e.level}`}>
                  <span className="log-row__time">
                    {new Date(e.time).toLocaleTimeString()}
                  </span>
                  <span className={`log-row__level log-row__level--${e.level}`}>
                    {e.level}
                  </span>
                  <span className="log-row__source">{e.source}</span>
                  <span className="log-row__msg">{e.message}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
