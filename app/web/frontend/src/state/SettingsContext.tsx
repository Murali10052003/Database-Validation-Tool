import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { ValidationProfileName } from "../api/types";

export interface AppSettings {
  validationMode: ValidationProfileName;
  sampleRowsPerTable: number;
  tablesToValidate: string;
  packagesToValidate: string;
  sourceCharacterSet: string;
  targetCharacterSet: string;
  allowedRowCountDiffPct: number;
  allowedDataMismatchPct: number;
  allowedEncodingIssuesPct: number;
  requireIdenticalByteLengths: boolean;
  allowKnownExceptions: boolean;
}

export const DEFAULT_SETTINGS: AppSettings = {
  validationMode: "standard",
  sampleRowsPerTable: 10,
  tablesToValidate: "",
  packagesToValidate: "",
  sourceCharacterSet: "AL32UTF8",
  targetCharacterSet: "UTF-8",
  allowedRowCountDiffPct: 0,
  allowedDataMismatchPct: 0,
  allowedEncodingIssuesPct: 0.1,
  requireIdenticalByteLengths: false,
  allowKnownExceptions: true,
};

interface SettingsCtx {
  settings: AppSettings;
  save: (next: AppSettings) => void;
  reset: () => void;
}

const SettingsContext = createContext<SettingsCtx | null>(null);
const STORAGE_KEY = "mv.settings";

function load(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<AppSettings>) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(load);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }, [settings]);

  const save = useCallback((next: AppSettings) => setSettings(next), []);
  const reset = useCallback(() => setSettings(DEFAULT_SETTINGS), []);

  const value = useMemo(() => ({ settings, save, reset }), [settings, save, reset]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): SettingsCtx {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used within SettingsProvider");
  return ctx;
}
