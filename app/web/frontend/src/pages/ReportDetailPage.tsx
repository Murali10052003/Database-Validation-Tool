import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { ValidationReport } from "../api/types";
import { api } from "../api/client";
import { Topbar } from "../components/layout/Topbar";
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { ResultsPanel } from "../components/validation/ResultsPanel";
import { formatDateTime, formatDuration, statusTone } from "../utils/format";

export function ReportDetailPage() {
  const { id = "" } = useParams();
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .getReport(id)
      .then((r) => active && setReport(r))
      .catch((e: Error) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  return (
    <>
      <Topbar title="Report" subtitle={report?.migration_name ?? id} />
      <div className="page">
        <Link to="/reports" className="link back-link">
          ← Back to reports
        </Link>

        {loading ? (
          <Card>
            <div className="empty">Loading…</div>
          </Card>
        ) : error ? (
          <Card>
            <div className="empty">{error}</div>
          </Card>
        ) : report ? (
          <Card
            title={report.migration_name}
            subtitle={`${formatDateTime(report.generated_at)} · ${report.profile} · ${formatDuration(report.duration_ms)}`}
            actions={
              <Badge tone={statusTone(report.overall_status)}>
                OVERALL: {report.overall_status}
              </Badge>
            }
          >
            <ResultsPanel report={report} />
          </Card>
        ) : null}
      </div>
    </>
  );
}
