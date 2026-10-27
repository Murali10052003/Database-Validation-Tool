import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ReportListItem, ValidationReport, ValidationStatus } from "../api/types";
import { api } from "../api/client";
import { Topbar } from "../components/layout/Topbar";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { AlertIcon, ArrowRightIcon, DatabaseIcon, PlayIcon, RefreshIcon } from "../components/ui/icons";
import { buildReportModel } from "../components/validation/reportModel";
import { useSavedConnections } from "../data/savedConnections";
import { formatDateTime, formatDuration, statusTone } from "../utils/format";
import { dashboardStatus, dashboardStatusLabels, newestReports } from "./dashboardModel";
import "../styles/dashboard.css";

const engineNames = {
  oracle: "Oracle", mysql: "MySQL", sqlserver: "SQL Server",
  azure_postgresql: "PostgreSQL", azure_sql: "Azure SQL", azure_mysql: "Azure MySQL",
};

export function DashboardPage() {
  const connections = useSavedConnections();
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [detail, setDetail] = useState<ValidationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ALL");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
    async function load() {
      try {
        const items = newestReports(await api.listReports());
        if (!active) return;
        setReports(items);
        setLoading(false);
        if (items.length) {
          setDetailLoading(true);
          try {
            const latest = await api.getReport(items[0].migration_id);
            if (active) setDetail(latest);
          } catch (reason) {
            if (active) setDetailError(reason instanceof Error ? reason.message : "Latest report details could not be loaded.");
          } finally {
            if (active) setDetailLoading(false);
          }
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Reports could not be loaded.");
          setLoading(false);
        }
      }
    }
    void load();
    return () => { active = false; };
  }, [refresh]);

  const latest = reports[0];
  const status = latest ? dashboardStatus(detail ?? latest) : "WARNING";
  const counts = detail?.summary;
  const issues = detail ? buildReportModel(detail).issues : [];
  const filtered = reports.filter(report => {
    const currentStatus = dashboardStatus(detail?.migration_id === report.migration_id ? detail : report);
    return (filter === "ALL" || currentStatus === filter) &&
      `${report.migration_name} ${report.profile} ${report.migration_id}`.toLowerCase().includes(query.trim().toLowerCase());
  });
  const reportPath = latest ? `/reports/${encodeURIComponent(latest.migration_id)}` : "/reports";

  return (
    <>
      <Topbar title="Dashboard" subtitle="Your migrations, connections, and latest results" />
      <div className="page dashboard">
        <div className="dashboard__toolbar">
          <span className="dashboard__muted">{loading ? "Loading validation runs..." : error ? "Validation history unavailable" : `${reports.length} validation runs`}</span>
          <div className="dashboard__actions">
            <Button size="sm" loading={loading || detailLoading} icon={<RefreshIcon size={15} />} onClick={() => setRefresh(value => value + 1)}>Refresh</Button>
            <Link className="btn btn--primary btn--sm" to="/run"><PlayIcon size={16} />Run validation</Link>
          </div>
        </div>

        {error ? <div className="dashboard__notice" role="alert">{error}</div> : loading ? <div className="dashboard__notice" role="status">Loading latest validation...</div> : latest ? (
          <section className={`dashboard__latest dashboard__latest--${statusTone(status)}`} aria-labelledby="latest-heading">
            <div className="dashboard__section-head">
              <div>
                <p className="dashboard__eyebrow">Latest validation report</p>
                <div className="dashboard__title-row"><h2 id="latest-heading">{latest.migration_name}</h2><StatusBadge status={status} /></div>
                <p className="dashboard__meta">{formatDateTime(latest.generated_at)} · {latest.profile.toUpperCase()} profile</p>
              </div>
              <Link className="btn btn--secondary btn--sm" to={reportPath}>View report<ArrowRightIcon size={16} /></Link>
            </div>
            <div className="dashboard__metrics">
              <Metric label="Failed checks" value={counts?.failed ?? latest.failed} tone="danger" />
              <Metric label="Warnings" value={counts?.warning ?? latest.warning} tone="warning" />
              <Metric label="Checks completed" value={counts ? `${counts.passed + counts.failed + counts.warning} / ${counts.total}` : "Unavailable"}
                note={counts ? `${counts.skipped} skipped · ${counts.not_supported} unsupported · ${counts.error} errors` : detailLoading ? "Loading coverage..." : "Coverage unavailable"} />
              <Metric label="Duration" value={formatDuration(detail?.duration_ms ?? latest.duration_ms)}
                note={detail?.coverage?.not_reached_stages.length ? `${detail.coverage.not_reached_stages.length} stages not reached` : undefined} />
            </div>
            {detailError && <p className="dashboard__detail-error" role="alert">Report details unavailable: {detailError}</p>}
          </section>
        ) : <section className="dashboard__notice"><h2>No validations yet</h2><Link to="/run" className="link">Run your first validation<ArrowRightIcon size={16} /></Link></section>}

        <section aria-labelledby="connections-heading">
          <div className="dashboard__section-head"><div className="dashboard__title-row"><h2 id="connections-heading">Saved connections</h2><span className="dashboard__count">{connections.length}</span></div><Link to="/run" className="link">Manage connections<ArrowRightIcon size={16} /></Link></div>
          {connections.length ? <div className="dashboard__connections">{connections.map(connection => (
            <article className="dashboard__connection" key={connection.id}>
              <div className="dashboard__connection-head"><span className="dashboard__database"><DatabaseIcon size={22} /></span><div><h3>{engineNames[connection.type]}</h3><p className="dashboard__meta">{connection.platform === "azure" ? "Azure" : connection.platform === "self_managed" ? "Self-managed" : "Platform unspecified"}</p></div></div>
              <dl><dt>Host</dt><dd>{connection.host || "Not specified"}</dd><dt>Database</dt><dd>{connection.database || connection.service || "Not specified"}</dd><dt>Port</dt><dd>{connection.port ?? "Default"}</dd></dl>
              <div className="dashboard__connection-footer"><span className="dashboard__muted">Saved profile</span><Link className="link" to="/run">Open validation<ArrowRightIcon size={15} /></Link></div>
            </article>
          ))}</div> : <div className="dashboard__notice"><p>No saved connections.</p><Link className="link" to="/run">Add a connection<ArrowRightIcon size={16} /></Link></div>}
        </section>

        <div className="dashboard__columns">
          <section aria-labelledby="activity-heading">
            <div className="dashboard__section-head"><h2 id="activity-heading">Recent validation activity</h2><Link className="link" to="/reports">All reports<ArrowRightIcon size={16} /></Link></div>
            <div className="dashboard__filters"><input type="search" aria-label="Search validation activity" placeholder="Search migrations..." value={query} onChange={event => setQuery(event.target.value)} /><select aria-label="Filter activity by status" value={filter} onChange={event => setFilter(event.target.value)}><option value="ALL">All statuses</option>{Object.entries(dashboardStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
            {loading ? <div className="empty">Loading activity...</div> : error ? <div className="empty">Activity unavailable.</div> : !filtered.length ? <div className="empty">{reports.length ? "No matching validation runs." : "No validation reports yet."}</div> : (
              <ul className="dashboard__activity">{filtered.slice(0, 6).map(report => (
                <li key={report.migration_id}><Link to={`/reports/${encodeURIComponent(report.migration_id)}`}>
                  <div><strong>{report.migration_name}</strong><p className="dashboard__meta">{formatDateTime(report.generated_at)} · {report.profile.toUpperCase()}</p></div>
                  <div className="dashboard__activity-status"><StatusBadge status={dashboardStatus(detail?.migration_id === report.migration_id ? detail : report)} /><p className="dashboard__meta">{report.failed} failed · {report.warning} warnings</p></div>
                </Link></li>
              ))}</ul>
            )}
            {!loading && !error && filtered.length > 6 && <p className="dashboard__meta">Showing 6 of {filtered.length} matching reports</p>}
          </section>

          <section aria-labelledby="attention-heading">
            <div className="dashboard__section-head"><div className="dashboard__title-row"><h2 id="attention-heading">Needs attention</h2>{detail && <span className="dashboard__count">{issues.length}</span>}</div></div>
            {!loading && !error && latest && <p className="dashboard__meta dashboard__scope">{latest.migration_name} · Latest report</p>}
            {loading || detailLoading ? <div className="empty">Loading findings...</div> : error || detailError ? <div className="empty">Findings unavailable. Refresh to retry.</div> : !detail ? <div className="empty">No validation report yet.</div> : (
              <>
                {issues.length ? <ul className="dashboard__findings">{issues.slice(0, 4).map((finding, index) => (
                  <li key={`${finding.check_id}-${index}`}><AlertIcon size={17} /><div><h3>{finding.message || finding.check_id}</h3><p className="dashboard__meta">{finding.source_object || finding.target_object || finding.category}</p><Link to={reportPath} className="link">View report<ArrowRightIcon size={14} /></Link></div><StatusBadge status={finding.status} /></li>
                ))}</ul> : <p className="empty">{detail.coverage?.not_reached_stages.length ? "Some validation stages were not reached. Review coverage in the report." : "No findings in this report."}</p>}
                <Link className="link dashboard__all-findings" to={reportPath}>Open latest report<ArrowRightIcon size={16} /></Link>
              </>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

function StatusBadge({ status }: { status: ValidationStatus }) {
  return <Badge tone={statusTone(status)}>{dashboardStatusLabels[status]}</Badge>;
}

function Metric({ label, value, tone = "muted", note }: { label: string; value: string | number; tone?: string; note?: string }) {
  return <div className={`dashboard__metric dashboard__metric--${tone}`}><div className="dashboard__metric-value">{value}</div><div className="dashboard__metric-label">{label}</div>{note && <p className="dashboard__meta">{note}</p>}</div>;
}
