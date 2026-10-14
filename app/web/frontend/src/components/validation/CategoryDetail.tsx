// Collapsible Category -> Object -> Check hierarchy for a single category.
//
// Default view stays compact: the category shows a summary line and its objects
// (e.g. tables), each collapsed. Only when a user expands an object are its
// individual checks rendered — so hundreds of PASS checks never load up-front.
// When a status filter or search is active the matching branches auto-expand so
// problems surface without extra clicks.

import { useMemo, useState } from "react";
import type { ValidationResult } from "../../api/types";
import type { CategoryGroup, ObjectGroup, StatusFilter } from "./reportModel";
import { checkLabel, filterChecks, groupStatus, healthPct } from "./reportModel";
import { CheckLinks, HealthBar, SourceTargetDiff, StatusPill } from "./parts";
import { ChevronIcon } from "../ui/icons";

interface Props {
  category: CategoryGroup;
  statusFilter: StatusFilter;
  query: string;
  defaultOpen?: boolean;
}

function isProblem(r: ValidationResult): boolean {
  return r.status !== "PASS";
}

export function CategoryDetail({ category, statusFilter, query, defaultOpen = false }: Props) {
  const filtering = statusFilter !== "ALL" || query.trim() !== "";
  const [open, setOpen] = useState(defaultOpen);

  const visibleObjects = useMemo(() => {
    if (!filtering) return category.objects;
    return category.objects
      .map((obj) => {
        const checks = filterChecks(obj.checks, statusFilter, query);
        return checks.length ? { ...obj, checks } : null;
      })
      .filter((o): o is ObjectGroup => o !== null);
  }, [category.objects, statusFilter, query, filtering]);

  if (category.counts.total === 0) return null;
  if (filtering && visibleObjects.length === 0) return null;

  const expanded = filtering || open;
  const matchCount = filtering
    ? visibleObjects.reduce((n, o) => n + o.checks.length, 0)
    : category.counts.total;

  return (
    <section className="vr-detail">
      <button
        type="button"
        className="vr-detail__head"
        aria-expanded={expanded}
        onClick={() => !filtering && setOpen((v) => !v)}
      >
        <ChevronIcon size={16} className={`vr-caret ${expanded ? "vr-caret--open" : ""}`} />
        <span className="vr-detail__title">{category.meta.label}</span>
        <StatusPill status={category.status} className="vr-detail__pill" />
        <span className="vr-detail__count">
          {filtering ? `${matchCount} matching` : `${category.counts.passed}/${category.counts.total} passed`}
        </span>
        {category.counts.failed > 0 && (
          <span className="vr-chip-count vr-chip-count--fail">{category.counts.failed} failed</span>
        )}
        {category.counts.warning > 0 && (
          <span className="vr-chip-count vr-chip-count--warn">{category.counts.warning} warning</span>
        )}
      </button>

      {expanded && (
        <div className="vr-detail__body">
          {visibleObjects.map((obj) => (
            <ObjectRow key={obj.key} object={obj} forceOpen={filtering} />
          ))}
        </div>
      )}
    </section>
  );
}

function ObjectRow({ object, forceOpen }: { object: ObjectGroup; forceOpen: boolean }) {
  const [open, setOpen] = useState(false);
  const expanded = forceOpen || open;
  const status = forceOpen ? groupStatus({ ...object.counts }) : object.status;

  return (
    <div className={`vr-obj ${expanded ? "vr-obj--open" : ""}`}>
      <button
        type="button"
        className="vr-obj__head"
        aria-expanded={expanded}
        onClick={() => !forceOpen && setOpen((v) => !v)}
      >
        <ChevronIcon size={14} className={`vr-caret ${expanded ? "vr-caret--open" : ""}`} />
        <span className="vr-obj__name">{object.label}</span>
        <StatusPill status={status} className="vr-obj__pill" />
        <span className="vr-obj__count">
          {object.counts.passed}/{object.counts.total}
        </span>
        <HealthBar
          value={healthPct(object.counts)}
          status={status}
          label={`${object.label} pass rate among evaluated checks`}
        />
      </button>

      {expanded && (
        <ul className="vr-check-list">
          {object.checks.map((r, i) => (
            <CheckRow key={`${r.check_id}-${i}`} result={r} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CheckRow({ result }: { result: ValidationResult }) {
  const problem = isProblem(result);
  return (
    <li className={`vr-check ${problem ? "vr-check--problem" : ""}`}>
      <div className="vr-check__head">
        <StatusPill status={result.status} />
        <span className="vr-check__name">{checkLabel(result)}</span>
        {result.severity && result.severity !== "INFO" && (
          <span className="vr-check__sev">{result.severity}</span>
        )}
      </div>
      {problem ? (
        <SourceTargetDiff result={result} />
      ) : result.message ? (
        <p className="vr-check__msg">{result.message}</p>
      ) : null}
      <CheckLinks result={result} />
    </li>
  );
}
