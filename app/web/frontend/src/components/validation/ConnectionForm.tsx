import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import type { AuthMethod, ConnectionCheck, ConnectionInput } from "../../api/types";
import { FIELD_DEFS, findDbType, type DbTypeDef, type FieldName } from "../../data/dbTypes";
import { saveConnection, type SavedConnection } from "../../data/savedConnections";
import { useToast } from "../../state/ToastContext";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { BookmarkIcon, DatabaseIcon } from "../ui/icons";
import { connectionEngineNames } from "./savedConnectionModel";
import { entraRedirectUri, forgetAccount, prepareEntra } from "../../auth/entra";

type Values = Partial<Record<FieldName | "entra_mode" | "entra_client_id" | "entra_tenant_id", string | boolean>>;

function seed(def: DbTypeDef): Values {
  const values: Values = {};
  for (const field of def.fields) {
    const preset = def.defaults?.[field];
    if (field === "ssl") values.ssl = preset === true;
    else if (field === "auth_method") values.auth_method = (preset as string) ?? "password";
    else values[field] = preset != null ? String(preset) : "";
  }
  return values;
}

function numOrNull(value: unknown): number | null {
  if (value === "" || value == null) return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

function build(def: DbTypeDef, values: Values): Partial<ConnectionInput> {
  const authMethod = (values.auth_method as ConnectionInput["auth_method"]) || "password";
  const conn: Partial<ConnectionInput> = {
    type: def.value,
    platform: def.platform,
    username: String(values.username ?? "").trim(),
    auth_method: authMethod,
    entra_mode: authMethod === "entra" && def.value === "azure_postgresql" && values.entra_mode === "local" ? "local" : "browser",
    ssl: values.ssl === true,
    host: String(values.host ?? "").trim(),
    port: numOrNull(values.port ?? def.defaults?.port),
  };
  if (def.fields.includes("service"))
    conn.service = String(values.service ?? "").trim() || null;
  if (def.fields.includes("database"))
    conn.database = String(values.database ?? "").trim() || null;
  conn.password = authMethod === "entra" ? "" : String(values.password ?? "");
  if (authMethod === "entra" && def.value === "azure_postgresql" && conn.entra_mode === "browser") {
    conn.entra_client_id = String(values.entra_client_id ?? "").trim();
    conn.entra_tenant_id = String(values.entra_tenant_id ?? "").trim();
  }
  return conn;
}

interface ConnectionFormProps {
  title: string;
  dbTypes: DbTypeDef[];
  check: ConnectionCheck | null;
  onChange: (conn: Partial<ConnectionInput>) => void;
  load?: { conn: SavedConnection; nonce: number } | null;
  onSaved?: (connection: SavedConnection) => void;
  metadataOnly?: boolean;
  savedLabel?: string;
  editingId?: string;
  onTest?: () => void;
  testing?: boolean;
  signedInAs?: string;
  onDisconnect?: () => void;
}

export function ConnectionForm({ title, dbTypes, check, onChange, load, onSaved, metadataOnly = false, savedLabel, editingId, onTest, testing, signedInAs, onDisconnect }: ConnectionFormProps) {
  const { push } = useToast();
  const [typeValue, setTypeValue] = useState(dbTypes[0].value);
  const def = useMemo(() => findDbType(dbTypes, typeValue), [dbTypes, typeValue]);
  const [values, setValues] = useState<Values>(() => seed(def));
  const [saveOpen, setSaveOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const saveDialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (saveOpen && !saveDialog.current?.open) saveDialog.current?.showModal();
    if (!saveOpen && saveDialog.current?.open) saveDialog.current.close();
  }, [saveOpen]);
  // Values to merge in once a pending engine switch has reseeded the form.
  const pending = useRef<Values | null>(null);

  useEffect(() => {
    const base = seed(def);
    if (pending.current) {
      setValues({ ...base, ...pending.current });
      pending.current = null;
    } else {
      setValues(base);
    }
  }, [def]);

  useEffect(() => {
    const connection = build(def, values);
    onChange(connection);
    return () => forgetAccount(connection);
  }, [def, values, onChange]);

  useEffect(() => {
    if (!metadataOnly) void prepareEntra(build(def, values)).catch(() => {});
  }, [def, values, metadataOnly]);

  const usesEntra = values.auth_method === "entra";

  const setField = (name: keyof Values, value: string | boolean) =>
    setValues((v) => ({ ...v, [name]: value }));

  function applySaved(sc: SavedConnection) {
    const next: Values = {
      host: sc.host ?? "",
      port: sc.port != null ? String(sc.port) : "",
      service: sc.service ?? "",
      database: sc.database ?? "",
      username: sc.username ?? "",
      auth_method: sc.auth_method ?? "password",
      ssl: !!sc.ssl,
      password: "",
      entra_mode: "browser",
    };
    if (sc.type === typeValue) {
      setValues({ ...seed(def), ...next });
    } else {
      pending.current = next;
      setTypeValue(sc.type);
    }
  }

  // Apply a saved connection requested from the Saved connections panel.
  useEffect(() => {
    if (load) applySaved(load.conn);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load?.nonce]);

  async function handleSave() {
    const host = String(values.host ?? "").trim();
    const username = String(values.username ?? "").trim();
    if (!host || !username) {
      push("Enter host and username before saving", "error");
      return;
    }
    const database = def.fields.includes("database")
      ? String(values.database ?? "").trim() || null
      : null;
    const service = def.fields.includes("service")
      ? String(values.service ?? "").trim() || null
      : null;
    const port = numOrNull(values.port ?? def.defaults?.port);
    if (port === null || !Number.isInteger(port) || port < 1 || port > 65535) {
      push("Enter a port between 1 and 65535 before saving", "error");
      return;
    }
    try {
    const saved = await saveConnection({
      id: editingId,
      label: savedLabel?.trim() || displayName.trim() || connectionEngineNames[def.value],
      type: def.value,
      platform: def.platform,
      host,
      port,
      service,
      database,
      username,
      auth_method: (values.auth_method as AuthMethod) || "password",
      ssl: values.ssl === true,
    });
    push("Connection saved — password is never stored", "success");
    onSaved?.(saved);
    setSaveOpen(false);
    } catch (reason) { push(String(reason), "error"); }
  }

  return (
    <section className="card conn-card">
      <header className="card__head">
        <div className="conn-card__title">
          <span className={`conn-card__icon conn-card__icon--${def.platform}`}>
            <DatabaseIcon size={16} />
          </span>
          <h2 className="card__title">{title}</h2>
        </div>
        {check && (
          <Badge tone={check.success ? "success" : "danger"}>
            {check.success ? "CONNECTED" : "FAILED"}
          </Badge>
        )}
      </header>

      <div className="card__body">
        <div className="field field--full">
          <span className="field__label">Database engine</span>
          <select
            className="input select"
            aria-label={`${title} database engine`}
            value={typeValue}
            onChange={(e) => setTypeValue(e.target.value as DbTypeDef["value"])}
          >
            {dbTypes.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </div>

        <div className="conn-grid">
          {def.fields.map((name) => {
            const fdef = FIELD_DEFS[name];
            if (!fdef || name === "ssl") return null;
            if (name === "password" && (usesEntra || metadataOnly)) return null;

            if (fdef.type === "checkbox") {
              return (
                <label key={name} className="checkbox conn-grid__full">
                  <input
                    type="checkbox"
                    checked={values.ssl === true}
                    onChange={(e) => setField(name, e.target.checked)}
                  />
                  <span className="checkbox__body">
                    <span className="checkbox__label">{fdef.label}</span>
                  </span>
                </label>
              );
            }

            if (fdef.type === "select") {
              return (
                <label key={name} className="field">
                  <span className="field__label">{fdef.label}</span>
                  <select
                    className="input select"
                    value={String(values[name] ?? "")}
                    onChange={(e) => setField(name, e.target.value)}
                  >
                    {fdef.options!.map(([v, text]) => (
                      <option key={v} value={v}>
                        {text}
                      </option>
                    ))}
                  </select>
                </label>
              );
            }

            return (
              <label key={name} className="field">
                <span className="field__label">{fdef.label}</span>
                <input
                  className="input"
                  type={fdef.type}
                  placeholder={fdef.placeholder}
                  value={String(values[name] ?? "")}
                  onChange={(e) => setField(name, e.target.value)}
                />
              </label>
            );
          })}
        </div>

        {usesEntra && def.value === "azure_postgresql" && !metadataOnly && (
          <>
          <label className="field">
            <span className="field__label">Entra credential source</span>
            <select className="input select" value={String(values.entra_mode || "browser")}
              onChange={event => setField("entra_mode", event.target.value)}>
              <option value="browser">Browser sign-in</option>
              <option value="local">Local developer credentials</option>
            </select>
          </label>
          {values.entra_mode !== "local" && (
            <div className="conn-grid">
              <label className="field">
                <span className="field__label">Application (client) ID</span>
                <input className="input" type="text" autoComplete="off" spellCheck={false}
                  value={String(values.entra_client_id || "")}
                  onChange={event => setField("entra_client_id", event.target.value)} />
              </label>
              <label className="field">
                <span className="field__label">Directory (tenant) ID</span>
                <input className="input" type="text" autoComplete="off" spellCheck={false}
                  value={String(values.entra_tenant_id || "")}
                  onChange={event => setField("entra_tenant_id", event.target.value)} />
              </label>
              <label className="field conn-grid__full">
                <span className="field__label">SPA redirect URI</span>
                <input className="input" type="text" readOnly value={entraRedirectUri()}
                  onFocus={event => event.target.select()} />
              </label>
            </div>
          )}
          </>
        )}

        <div className="conn-save">
          {onTest && <Button variant="secondary" icon={<DatabaseIcon size={14} />} loading={testing} onClick={onTest}>Test {title.toLowerCase()} connection</Button>}
          <button type="button" className="conn-save__btn" onClick={() => {
            if (metadataOnly) handleSave();
            else { setDisplayName(connectionEngineNames[def.value]); setSaveOpen(true); }
          }}>
            <BookmarkIcon size={14} />
            Save connection
          </button>
        </div>

        {usesEntra && signedInAs && <div className="conn-account"><span>Signed in as {signedInAs}</span><Button variant="secondary" onClick={onDisconnect}>Disconnect account</Button></div>}

        {check && (
          <div className="conn-detail">
            <div className="kv">
              <span>Version</span>
              <span>{check.version || "—"}</span>
            </div>
            <div className="kv">
              <span>Latency</span>
              <span>{check.latency_ms != null ? `${check.latency_ms} ms` : "—"}</span>
            </div>
            <div className="kv">
              <span>Detail</span>
              <span>{check.error || check.message || "—"}</span>
            </div>
          </div>
        )}
      </div>
      {!metadataOnly && <dialog ref={saveDialog} className="connections-dialog" aria-label={`Save ${title.toLowerCase()} connection`} onCancel={() => setSaveOpen(false)} onClose={() => setSaveOpen(false)}>
        <header className="connections__head"><h2>Save connection</h2><button type="button" className="connections-icon" title="Close dialog" aria-label="Close save dialog" onClick={() => setSaveOpen(false)}><X size={18} /></button></header>
        <form onSubmit={event => { event.preventDefault(); handleSave(); }}>
          <label className="field"><span className="field__label">Display name</span><input autoFocus className="input" required maxLength={40} value={displayName} onChange={event => setDisplayName(event.target.value)} /></label>
          <div className="connections-dialog__actions"><button type="button" className="btn btn--secondary btn--sm" onClick={() => setSaveOpen(false)}>Cancel</button><button type="submit" className="btn btn--primary btn--sm" disabled={!displayName.trim()}>Save</button></div>
        </form>
      </dialog>}
    </section>
  );
}
