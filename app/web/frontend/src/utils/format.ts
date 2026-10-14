import type { ValidationStatus } from "../api/types";

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

export function statusTone(status: ValidationStatus): "success" | "danger" | "warning" | "muted" {
  switch (status) {
    case "PASS":
      return "success";
    case "FAIL":
      return "danger";
    case "ERROR":
      return "danger";
    case "WARNING":
      return "warning";
    default:
      return "muted";
  }
}

export function pct(part: number, total: number): number {
  if (!total) return 0;
  return Math.round((part / total) * 100);
}
