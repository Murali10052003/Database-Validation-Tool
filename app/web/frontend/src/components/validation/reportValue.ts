export function reportValue(value: unknown): string {
  if (value === null || value === undefined) return "Not recorded";
  if (value === "") return '""';
  return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
}