import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ArrowRight, ChevronLeft, ChevronRight, Download, FileText, ScrollText, Search, X } from "lucide-react";
import type { ValidationReport, ValidationResult } from "../../api/types";
import { api } from "../../api/client";
import { buildReportModel, CATEGORY_LABEL, categoryOf, matchesStatus, type StatusFilter } from "./reportModel";
import { ReportNavigation, CheckLinks, SourceTargetDiff, StatusPill } from "./parts";
import { ReportCheckTable } from "./ReportCheckTable";
import { reportValue } from "./reportValue";
import "../../styles/report-details.css";

type View = "overview" | "checks" | "scope";
type Filter = StatusFilter | "ISSUES";
const tabs: { id: View; label: string }[] = [{ id: "overview", label: "Overview" }, { id: "checks", label: "Check results" }, { id: "scope", label: "Run scope" }];
const filters: { id: Filter; label: string }[] = [
  { id: "ALL", label: "All statuses" }, { id: "ISSUES", label: "Needs attention" },
  { id: "FAILED", label: "Failed" }, { id: "WARNING", label: "Warnings" }, { id: "ERROR", label: "Errors" },
  { id: "SKIPPED", label: "Skipped" }, { id: "NOT_SUPPORTED", label: "Not supported" }, { id: "PASSED", label: "Passed" },
];
const pageSize = 10;

function nextAction(result: ValidationResult) {
  switch (result.status) {
    case "ERROR": return "Investigate the execution error and required connectivity or permissions before rerunning.";
    case "NOT_SUPPORTED": return "Arrange an independent check or add validated support; this check is not a pass.";
    case "SKIPPED": return "Confirm the exclusion, missing target or configured limit is intentional before sign-off.";
    case "FAIL": return "Review the source/target difference and mapping, correct the mismatch, then rerun.";
    case "WARNING": return "Review this warning against the migration acceptance criteria.";
    default: return "No corrective action indicated by this check.";
  }
}

function downloadJson(report: ValidationReport) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `migration-${report.migration_id}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportDetails({ report }: { report: ValidationReport }) {
  const model = useMemo(() => buildReportModel(report), [report]);
  const [view, setView] = useState<View>("overview");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState<Filter>("ALL");
  const [severity, setSeverity] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [inspection, setInspection] = useState<{ checks: ValidationResult[]; index: number } | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const inspectTrigger = useRef<HTMLElement | null>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const counts = model.counts;
  const evaluated = counts.passed + counts.failed + counts.warning;
  const active = inspection?.checks[inspection.index];
  const populated = model.categories.filter(group => group.counts.total > 0);
  const ordered = [...model.issues, ...report.results.filter(result => result.status === "PASS")];
  const search = query.trim().toLowerCase();
  const results = ordered.filter(result => (category === "all" || categoryOf(result) === category) &&
    (status === "ISSUES" ? result.status !== "PASS" : matchesStatus(result, status)) &&
    (!severity || result.severity === severity) &&
    (!search || [result.source_object, result.target_object, result.check_id, result.message, result.error,
      ...(result.differences ?? []), reportValue(result.source_value), reportValue(result.target_value)]
      .some(value => value?.toLowerCase().includes(search))));
  const pages = Math.max(1, Math.ceil(results.length / pageSize));
  const currentPage = Math.min(page, pages - 1);
  const visible = results.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const preview = model.issues.slice(0, 4);

  useEffect(() => {
    if (inspection && !dialog.current?.open) dialog.current?.showModal();
    if (!inspection && dialog.current?.open) dialog.current.close();
    if (dialog.current) dialog.current.scrollTop = 0;
  }, [inspection]);

  function inspect(result: ValidationResult, sequence: ValidationResult[]) {
    inspectTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setInspection({ checks: sequence, index: sequence.indexOf(result) });
  }
  function closeInspection() {
    dialog.current?.close();
    setInspection(null);
    inspectTrigger.current?.focus();
  }
  function showChecks(nextCategory = "all", nextStatus: Filter = "ALL") {
    setCategory(nextCategory); setStatus(nextStatus); setSeverity(""); setQuery(""); setPage(0); setView("checks");
    tabRefs.current[1]?.focus();
  }

  return <ReportNavigation.Provider value={{ runId: report.run_id }}>
    <div className="report-details">
      <section className={`report-summary report-summary--${report.overall_status.toLowerCase()}`} aria-label="Validation outcome">
        <div className="report-section-head"><div><h2>Validation outcome <StatusPill status={report.overall_status} /></h2><p>{counts.failed} failed checks · {counts.error} execution errors · {counts.warning} warnings</p></div>
          <div className="report-actions">
            {report.run_id && <a className="btn btn--secondary btn--sm" href={`#/logs?run=${encodeURIComponent(report.run_id)}`}><ScrollText size={15} />Run logs</a>}
            <a className="btn btn--secondary btn--sm" href={api.reportUrl(report.migration_id, "html")} target="_blank" rel="noreferrer"><FileText size={15} />View HTML</a>
            <a className="btn btn--secondary btn--sm" href={api.reportUrl(report.migration_id, "csv")}><Download size={15} />CSV</a>
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => downloadJson(report)}><Download size={15} />JSON</button>
          </div>
        </div>
        <div className="report-metrics">
          {([{ value: counts.failed, label: "Failed checks", status: "FAILED", tone: "fail" }, { value: counts.warning, label: "Warnings", status: "WARNING", tone: "warning" }, { value: counts.skipped, label: "Skipped checks", status: "SKIPPED", tone: "muted" }, { value: counts.passed, label: "Passed checks", status: "PASSED", tone: "pass" }] as const).map(metric => <button type="button" className={`report-metric report-metric--${metric.tone}`} key={metric.label} onClick={() => showChecks("all", metric.status)}><strong>{metric.value}</strong><span>{metric.label}<ArrowRight size={13} /></span></button>)}
        </div>
        <div className="report-coverage-line"><strong>{evaluated} / {counts.total} emitted checks evaluated</strong><button type="button" className="report-link" onClick={() => showChecks("all", "ERROR")}>{counts.error} errors</button><button type="button" className="report-link" onClick={() => showChecks("all", "NOT_SUPPORTED")}>{counts.notSupported} unsupported</button><button type="button" className="report-link" onClick={() => { setView("scope"); tabRefs.current[2]?.focus(); }}>Run scope<ArrowRight size={14} /></button></div>
        {!!report.coverage?.not_reached_stages.length && <p className="report-coverage-warning">{report.coverage.not_reached_stages.length} selected stages were not reached.</p>}
        {report.coverage?.metadata_warning && <p className="report-coverage-warning">{report.coverage.metadata_warning}</p>}
        {!counts.total && <p className="report-coverage-warning">No emitted checks. Validation coverage cannot be established.</p>}
      </section>

      <div className="report-tabs" role="tablist" aria-label="Report views" onKeyDown={event => {
        const current = tabs.findIndex(tab => tab.id === view);
        const next = event.key === "ArrowRight" ? (current + 1) % tabs.length : event.key === "ArrowLeft" ? (current + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
        if (next !== null) { event.preventDefault(); setView(tabs[next].id); tabRefs.current[next]?.focus(); }
      }}>{tabs.map((tab, index) => <button type="button" key={tab.id} ref={element => { tabRefs.current[index] = element; }} id={`${id}-${tab.id}`} role="tab" aria-selected={view === tab.id} tabIndex={view === tab.id ? 0 : -1} aria-controls={`${id}-panel`} onClick={() => setView(tab.id)}>{tab.label}{tab.id === "checks" && <span>{report.results.length}</span>}</button>)}</div>
      <section id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${view}`}>
        {view === "overview" && <>
          <div className="report-section-head"><div><h2>Needs attention</h2><p>Failures, execution errors, warnings and coverage gaps</p></div><button type="button" className="btn btn--secondary btn--sm" onClick={() => showChecks("all", "ISSUES")}>View all issues ({model.issues.length})<ArrowRight size={14} /></button></div>
          {preview.length ? <ReportCheckTable checks={preview} compact onInspect={result => inspect(result, preview)} /> : <p className="report-empty">No issues in emitted checks. Review run scope for coverage.</p>}
          <div className="report-section-head"><div><h2>Validation categories</h2><p>{report.results.length} emitted checks across {populated.length} categories</p></div></div>
          <div className="report-table-scroll" tabIndex={0} role="region" aria-label="Category summary"><table className="report-table report-category-table"><thead><tr><th>Category</th><th>Outcome</th><th>Passed</th><th>Failed</th><th>Warnings</th><th>Errors</th><th>Skipped</th><th>Unsupported</th><th>Evaluated</th><th><span className="report-visually-hidden">Actions</span></th></tr></thead><tbody>{populated.map(group => <tr key={group.meta.id}><td><strong>{group.meta.label}</strong></td><td><StatusPill status={group.status} /></td>{(["passed", "failed", "warning", "error", "skipped", "notSupported"] as const).map(key => <td key={key} className={!group.counts[key] ? "report-zero" : ""}>{group.counts[key]}</td>)}<td>{group.counts.passed + group.counts.failed + group.counts.warning} / {group.counts.total}</td><td><button type="button" className="report-link" aria-label={`View ${group.meta.label} checks`} onClick={() => showChecks(group.meta.id)}>View checks<ArrowRight size={14} /></button></td></tr>)}</tbody></table></div>
        </>}
        {view === "checks" && <>
          <div className="report-section-head"><div><h2>{populated.find(group => group.meta.id === category)?.meta.label ?? "All check results"}</h2><p>{results.length} matching checks</p></div><button type="button" className="report-link" onClick={() => showChecks()}>Reset filters</button></div>
          <div className="report-filters"><label className="report-search"><Search size={15} /><input className="input" aria-label="Search checks" type="search" placeholder="Search object, column or finding..." value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /></label><select className="input" aria-label="Check category" value={category} onChange={event => { setCategory(event.target.value); setPage(0); }}><option value="all">All categories</option>{populated.map(group => <option key={group.meta.id} value={group.meta.id}>{group.meta.label}</option>)}</select><select className="input" aria-label="Check status" value={status} onChange={event => { setStatus(event.target.value as Filter); setPage(0); }}>{filters.map(filter => <option key={filter.id} value={filter.id}>{filter.label}</option>)}</select><select className="input" aria-label="Check severity" value={severity} onChange={event => { setSeverity(event.target.value); setPage(0); }}><option value="">All severities</option>{[...new Set(report.results.map(result => result.severity).filter(Boolean))].map(value => <option key={value}>{value}</option>)}</select></div>
          <ReportCheckTable checks={visible} onInspect={result => inspect(result, results)} />
          <div className="report-pagination"><span role="status">{results.length ? `Showing ${currentPage * pageSize + 1}-${Math.min((currentPage + 1) * pageSize, results.length)} of ${results.length} checks` : "0 matching checks"}</span><div className="report-actions"><button type="button" className="report-icon" title="Previous page" aria-label="Previous page" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={16} /></button><span>{currentPage + 1} / {pages}</span><button type="button" className="report-icon" title="Next page" aria-label="Next page" disabled={currentPage === pages - 1} onClick={() => setPage(currentPage + 1)}><ChevronRight size={16} /></button></div></div>
        </>}
        {view === "scope" && <>
          <div className="report-section-head"><h2>Run scope and coverage</h2></div>
          <dl className="report-scope"><dt>Profile</dt><dd>{report.profile}</dd><dt>Started</dt><dd>{report.started_at || "Not recorded"}</dd><dt>Finished</dt><dd>{report.finished_at || "Not recorded"}</dd><dt>Duration</dt><dd>{report.duration_ms == null ? "Not recorded" : `${report.duration_ms} ms`}</dd><dt>Emitted checks</dt><dd>{counts.total}</dd><dt>Evaluated checks</dt><dd>{evaluated}</dd>
            {report.coverage && <><dt>Included objects</dt><dd>{report.coverage.included_objects?.join(", ") || "All objects"}</dd></>}
            {report.coverage && <><dt>Metadata mode</dt><dd>{report.coverage.discovery_mode || "Not recorded"}</dd><dt>Source inventory</dt><dd>{report.coverage.source_inventory_id || "Not recorded"}</dd><dt>Target inventory</dt><dd>{report.coverage.target_inventory_id || "Not recorded"}</dd><dt>Mapping version</dt><dd>{report.coverage.mapping_version_id || "Not recorded"}</dd></>}
            {report.coverage && <><dt>Selected stages</dt><dd>{report.coverage.selected_stages.join(", ") || "None"}</dd><dt>Reached stages</dt><dd>{report.coverage.reached_stages.join(", ") || "None"}</dd><dt>Not selected</dt><dd>{report.coverage.not_selected_stages.join(", ") || "None"}</dd><dt>Not reached</dt><dd>{report.coverage.not_reached_stages.join(", ") || "None"}</dd><dt>Exclusions</dt><dd>{report.coverage.excluded_objects.join(", ") || "None"}</dd><dt>Disabled schema checks</dt><dd>{Object.entries(report.coverage.schema_options).filter(([, enabled]) => !enabled).map(([name]) => name).join(", ") || "None"}</dd>{report.coverage.sample_limit != null && <><dt>Sample limit (historical)</dt><dd>{report.coverage.sample_limit}</dd></>}<dt>Checksum limit</dt><dd>{report.coverage.checksum_limit}</dd><dt>Snapshot consistency</dt><dd>{report.coverage.snapshot_consistent ? "Guaranteed" : "Not guaranteed"}</dd></>}
          </dl>
          {!report.coverage && <p className="report-empty">Coverage not recorded. This historical report has no stage or row-coverage manifest.</p>}
          <p className="report-scope-note">Skipped and unsupported checks are not passes. Emitted check coverage is not full migration readiness.</p>
        </>}
      </section>
      <dialog ref={dialog} className="report-inspect" aria-labelledby={`${id}-inspect-title`} onCancel={event => { event.preventDefault(); closeInspection(); }} onClose={() => setInspection(null)} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeInspection(); } }}>
        <header className="report-inspect__head"><h2 id={`${id}-inspect-title`}>Check details</h2><button type="button" className="report-icon" title="Close details" aria-label="Close details" onClick={closeInspection}><X size={18} /></button></header>
        {active && inspection && <div className="report-inspect__body"><StatusPill status={active.status} /><h3 className="report-inspect__object">{active.source_object || active.target_object || active.check_id}</h3><p className="report-inspect__subtitle">{CATEGORY_LABEL[categoryOf(active)]} · {active.check_id} · {active.severity}</p>
          <dl className="report-scope report-check-meta"><dt>Source object</dt><dd>{active.source_object || "Not recorded"}</dd><dt>Target object</dt><dd>{active.target_object || "Not recorded"}</dd></dl>
          <h3>Source and target</h3>
          <div className="report-comparison"><div><span>Source</span><pre>{reportValue(active.source_value)}</pre></div><div><span>Target</span><pre>{reportValue(active.target_value)}</pre></div></div>
          <h3>Finding</h3><SourceTargetDiff result={{ ...active, source_value: undefined, target_value: undefined }} />
          {!active.message && !active.error && !active.differences?.length && <p>No finding recorded.</p>}
          <h3>{active.status === "SKIPPED" || active.status === "NOT_SUPPORTED" ? "Coverage follow-up" : "Recommended next action"}</h3><p>{nextAction(active)}</p>
          <dl className="report-scope report-check-meta"><dt>Validation scope</dt><dd>{active.validation_scope || "Not recorded"}</dd><dt>Duration</dt><dd>{active.duration_ms == null ? "Not recorded" : `${active.duration_ms} ms`}</dd><dt>Duration scope</dt><dd>{active.duration_scope || "Not recorded"}</dd></dl>
          {active.coverage && <><h3>Check coverage</h3><pre className="report-check-coverage">{JSON.stringify(active.coverage, null, 2)}</pre></>}
          <CheckLinks result={active} />
          <footer className="report-inspect__footer"><span>{inspection.index + 1} of {inspection.checks.length} checks in this view</span><div className="report-actions"><button type="button" className="report-icon" title="Previous check" aria-label="Previous check" disabled={inspection.index === 0} onClick={() => setInspection({ ...inspection, index: inspection.index - 1 })}><ChevronLeft size={16} /></button><button type="button" className="report-icon" title="Next check" aria-label="Next check" disabled={inspection.index === inspection.checks.length - 1} onClick={() => setInspection({ ...inspection, index: inspection.index + 1 })}><ChevronRight size={16} /></button><button type="button" className="btn btn--secondary btn--sm" onClick={closeInspection}>Close</button></div></footer>
        </div>}
      </dialog>
    </div>
  </ReportNavigation.Provider>;
}