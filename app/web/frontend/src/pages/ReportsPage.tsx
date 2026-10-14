import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { ReportListItem } from "../api/types";
import { api } from "../api/client";
import { Topbar } from "../components/layout/Topbar";
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { RefreshIcon } from "../components/ui/icons";
import { formatDateTime, formatDuration, statusTone } from "../utils/format";
import { useToast } from "../state/ToastContext";

export function ReportsPage() {
  const { push } = useToast();
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      setReports(await api.listReports());
    } catch (err) {
      push(err instanceof Error ? err.message : "Failed to load reports", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return reports;
    return reports.filter(
      (r) =>
        r.migration_name.toLowerCase().includes(q) ||
        r.migration_id.toLowerCase().includes(q),
    );
  }, [reports, query]);

  return (
    <>
      <Topbar title="Reports" subtitle="Saved validation results" />
      <div className="page">
        <Card
          title={`All reports (${reports.length})`}
          actions={
            <Button size="sm" variant="ghost" icon={<RefreshIcon size={15} />} onClick={load}>
              Refresh
            </Button>
          }
        >
          <input
            className="input search search--wide"
            placeholder="Search by name or id…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="table-wrap">
            <table className="rtable">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Migration</th>
                  <th>Profile</th>
                  <th>Pass / Total</th>
                  <th>Failed</th>
                  <th>Duration</th>
                  <th>Generated</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={7} className="rtable__empty">
                      Loading…
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="rtable__empty">
                      No reports found
                    </td>
                  </tr>
                ) : (
                  rows.map((r) => (
                    <tr key={r.migration_id}>
                      <td>
                        <Badge tone={statusTone(r.overall_status)}>{r.overall_status}</Badge>
                      </td>
                      <td>
                        <Link className="link" to={`/reports/${r.migration_id}`}>
                          {r.migration_name}
                        </Link>
                        <div className="rtable__sub">{r.migration_id}</div>
                      </td>
                      <td>{r.profile}</td>
                      <td>
                        {r.passed} / {r.total}
                      </td>
                      <td>{r.failed}</td>
                      <td>{formatDuration(r.duration_ms)}</td>
                      <td>{formatDateTime(r.generated_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
