import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ActivityLevel = "info" | "success" | "warning" | "error";

export interface ActivityEntry {
  id: number;
  time: string;
  level: ActivityLevel;
  source: string;
  message: string;
}

interface ActivityCtx {
  entries: ActivityEntry[];
  log: (level: ActivityLevel, source: string, message: string) => void;
  clear: () => void;
}

const ActivityContext = createContext<ActivityCtx | null>(null);
const STORAGE_KEY = "mv.activity";
const MAX_ENTRIES = 300;
let nextId = 1;

function load(): ActivityEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as ActivityEntry[]) : [];
    if (parsed.length) nextId = Math.max(...parsed.map((e) => e.id)) + 1;
    return parsed;
  } catch {
    return [];
  }
}

export function ActivityProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<ActivityEntry[]>(load);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  }, [entries]);

  const log = useCallback(
    (level: ActivityLevel, source: string, message: string) => {
      setEntries((list) =>
        [
          { id: nextId++, time: new Date().toISOString(), level, source, message },
          ...list,
        ].slice(0, MAX_ENTRIES),
      );
    },
    [],
  );

  const clear = useCallback(() => setEntries([]), []);

  const value = useMemo(() => ({ entries, log, clear }), [entries, log, clear]);
  return <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>;
}

export function useActivity(): ActivityCtx {
  const ctx = useContext(ActivityContext);
  if (!ctx) throw new Error("useActivity must be used within ActivityProvider");
  return ctx;
}
