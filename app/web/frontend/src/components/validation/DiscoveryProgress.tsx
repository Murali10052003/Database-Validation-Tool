import type { PlanProgress } from "../../api/types";

// Live progress of a running Discover & match request.
export function DiscoveryProgress({ progress }: { progress: PlanProgress }) {
  const percent = Math.min(100, Math.max(0, Math.round(progress.percent ?? 0)));
  return (
    <div className="discovery-progress" role="status" aria-live="polite">
      <div className="discovery-progress__head">
        <span>{progress.stage || "Starting discovery"}</span>
        <strong>{percent}%</strong>
      </div>
      <div className="discovery-progress__bar" role="progressbar" aria-label="Discovery progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <div className="discovery-progress__fill" style={{ width: `${percent}%` }} />
      </div>
      {progress.message && <p className="field__hint">{progress.message}</p>}
    </div>
  );
}
