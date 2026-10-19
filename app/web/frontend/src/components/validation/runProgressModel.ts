import type { RunEvent } from "../../api/types";

export function visibleRunStages(events: RunEvent[]): string[] {
  return [...new Set(events.map(event => event.stage))]
    .filter(stage => stage !== "custom_query");
}