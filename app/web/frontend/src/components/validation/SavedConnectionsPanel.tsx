import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Info, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import type { ConnectionInput } from "../../api/types";
import { SOURCE_DB_TYPES, TARGET_DB_TYPES } from "../../data/dbTypes";
import { connectionStorageError, importLegacyConnections, legacyConnections, refreshConnections, deleteConnection, saveConnection, useSavedConnections, type SavedConnection } from "../../data/savedConnections";
import { useToast } from "../../state/ToastContext";
import { CheckIcon, DatabaseIcon } from "../ui/icons";
import { ConnectionForm } from "./ConnectionForm";
import { connectionEngineNames, matchesConnection, visibleConnections } from "./savedConnectionModel";
import "../../styles/connections.css";

type Modal = { kind: "add" } | { kind: "details" | "rename" | "edit" | "delete"; connection: SavedConnection };
interface Props {
  source: Partial<ConnectionInput>;
  target: Partial<ConnectionInput>;
  onSource: (connection: SavedConnection) => void;
  onTarget: (connection: SavedConnection) => void;
  onDelete: (connection: SavedConnection) => void;
  compact?: boolean;
  revealToken?: number;
}
const ignoreChange = () => {};

export function SavedConnectionsPanel({ source, target, onSource, onTarget, onDelete, compact = false, revealToken = 0 }: Props) {
  const saved = useSavedConnections();
  const { push } = useToast();
  const [query, setQuery] = useState("");
  const [engine, setEngine] = useState("all");
  const [expanded, setExpanded] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(!compact);
  const [page, setPage] = useState(0);
  const [modal, setModal] = useState<Modal | null>(null);
  const [label, setLabel] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const visible = visibleConnections(saved, source, target, query, engine, compact || expanded);
  const pageCount = Math.max(1, Math.ceil(visible.total / 4));
  const currentPage = Math.min(page, pageCount - 1);
  const items = compact ? visible.items.slice(currentPage * 4, currentPage * 4 + 4) : visible.items;

  useEffect(() => {
    if (revealToken) {
      setLibraryOpen(true);
      setQuery("");
      setEngine("all");
      setPage(0);
    }
  }, [revealToken]);

  useEffect(() => {
    if (modal && !dialog.current?.open) dialog.current?.showModal();
    if (!modal && dialog.current?.open) dialog.current.close();
  }, [modal]);

  function added() {
    setModal(null);
    setQuery("");
    setEngine("all");
    setExpanded(false);
    setLibraryOpen(true);
    setPage(0);
  }

  return (
    <section className={`connections${compact ? " connections--compact" : ""}`} aria-labelledby="saved-heading">
      <div className="connections__head">
        <div className="connections__title">{compact && <button className="connections-icon" type="button" aria-label="Toggle saved connections" aria-expanded={libraryOpen} aria-controls="saved-library-content" onClick={() => setLibraryOpen(value => !value)}>{libraryOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</button>}<h2 id="saved-heading">Saved connections</h2><span className="connections__count">{saved.length}</span></div>
        <button ref={addButton} className="btn btn--primary btn--sm" type="button" onClick={() => { setLabel(""); setModal({ kind: "add" }); }}><Plus size={16} />Add connection</button>
      </div>
      <div id="saved-library-content" hidden={!libraryOpen}>
      {connectionStorageError() && <p role="alert">{connectionStorageError()} <button className="btn btn--secondary btn--sm" type="button" onClick={() => void refreshConnections()}>Retry</button></p>}
      {!!legacyConnections().length && <button className="btn btn--secondary btn--sm" type="button" onClick={async () => { try { await importLegacyConnections(); push("Browser profiles imported; browser copies retained", "success"); } catch (reason) { push(String(reason), "error"); } }}>Import browser connections</button>}
      <div className="connections__filters">
        <label className="connections__search"><Search size={16} /><input className="input" type="search" aria-label="Search saved connections" placeholder="Search connections..." value={query} onChange={event => { setQuery(event.target.value); setExpanded(false); setPage(0); }} /></label>
        <select className="input select" aria-label="Filter database engine" value={engine} onChange={event => { setEngine(event.target.value); setExpanded(false); setPage(0); }}><option value="all">All engines</option>{SOURCE_DB_TYPES.map(def => <option key={def.value} value={def.value}>{connectionEngineNames[def.value]}</option>)}</select>
      </div>
      <div className="connections__grid" id="saved-connection-cards">
        {items.map(connection => {
          const isSource = matchesConnection(connection, source);
          const isTarget = matchesConnection(connection, target);
          const supportsTarget = TARGET_DB_TYPES.some(def => def.value === connection.type);
          const name = connectionEngineNames[connection.type];
          return <article key={connection.id} className={`connection-profile${isSource ? " is-source" : ""}${isTarget ? " is-target" : ""}`}>
            <div className="connection-profile__head">
              <span className={`conn-card__icon conn-card__icon--${connection.platform}`}><DatabaseIcon size={22} /></span>
              <div className="connection-profile__title"><h3>{connection.label}</h3><p>{name} · {connection.ssl ? "TLS" : "No TLS"}</p></div>
              <button type="button" className="connections-icon" title="Edit connection" aria-label={`Edit ${connection.label}`} onClick={() => { setLabel(connection.label); setModal({ kind: "edit", connection }); }}><Pencil size={16} /></button>
              <button type="button" className="connections-icon" title="Connection details" aria-label={`Details for ${name} at ${connection.host}`} onClick={() => setModal({ kind: "details", connection })}><Info size={17} /></button>
              <button type="button" className="connections-icon" title="Delete connection" aria-label={`Delete ${name} at ${connection.host}`} onClick={() => setModal({ kind: "delete", connection })}><Trash2 size={16} /></button>
            </div>
            <dl>{[["Host", connection.host], [connection.type === "oracle" ? "Service" : "Database", connection.database || connection.service || "Not specified"], ["Account", connection.username]].map(([title, value]) => <div key={title}><dt>{title}</dt><dd title={value}>{value}</dd></div>)}</dl>
            <p className="connection-profile__state">{isSource || isTarget ? <><CheckIcon size={14} />Selected as {isSource && isTarget ? "source and target" : isSource ? "source" : "target"}</> : "Saved connection"}</p>
            <div className="connection-profile__actions">
              <button className={`btn btn--secondary btn--sm${isSource ? " chosen-source" : ""}`} type="button" aria-pressed={isSource} onClick={() => { onSource(connection); setPage(0); }}>Use as source</button>
              <button className={`btn btn--secondary btn--sm${isTarget ? " chosen-target" : ""}`} type="button" aria-pressed={isTarget} disabled={!supportsTarget} title={supportsTarget ? undefined : "Target supports Azure engines only"} onClick={() => { onTarget(connection); setPage(0); }}>Use as target</button>
            </div>
          </article>;
        })}
      </div>
      {!visible.total && <p className="connections__empty">{saved.length ? "No matching connections." : "No saved connections."}</p>}
      <div className="connections__footer"><span role="status">Showing {items.length} of {visible.total}{query || engine !== "all" ? " matching" : ""} connections</span>{compact ? <div className="connections__title"><button className="connections-icon" type="button" title="Previous page" aria-label="Previous connections page" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={16} /></button><span>Page {currentPage + 1} of {pageCount}</span><button className="connections-icon" type="button" title="Next page" aria-label="Next connections page" disabled={currentPage + 1 === pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight size={16} /></button></div> : visible.total > 3 && <button type="button" className="btn btn--secondary btn--sm" aria-expanded={expanded} aria-controls="saved-connection-cards" onClick={() => setExpanded(value => !value)}>{expanded ? "Show fewer" : `Show all (${visible.total})`}{expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button>}</div>
      </div>

      <dialog ref={dialog} className="connections-dialog" aria-labelledby="connection-dialog-title" onCancel={() => setModal(null)} onClose={() => setModal(null)}>
        <header className="connections__head"><h2 id="connection-dialog-title">{modal?.kind === "add" ? "Add connection" : modal?.kind === "edit" ? "Edit connection" : modal?.kind === "delete" ? "Delete connection?" : modal?.kind === "rename" ? "Rename connection" : "Connection details"}</h2><button type="button" className="connections-icon" title="Close dialog" aria-label="Close dialog" onClick={() => setModal(null)}><X size={18} /></button></header>
        {modal?.kind === "edit" && <>
          <label className="field"><span className="field__label">Display name</span><input className="input" maxLength={40} value={label} onChange={event => setLabel(event.target.value)} /></label>
          <ConnectionForm key={modal.connection.id} title="Connection" dbTypes={SOURCE_DB_TYPES} check={null} onChange={ignoreChange} metadataOnly savedLabel={label} editingId={modal.connection.id} load={{ conn: modal.connection, nonce: 1 }} onSaved={connection => {
            if (matchesConnection(modal.connection, source)) onSource(connection);
            if (matchesConnection(modal.connection, target)) {
              if (TARGET_DB_TYPES.some(def => def.value === connection.type)) onTarget(connection);
              else onDelete(modal.connection);
            }
            added();
          }} />
        </>}
        {modal?.kind === "add" && <>
          <label className="field"><span className="field__label">Display name (optional)</span><input className="input" maxLength={40} value={label} onChange={event => setLabel(event.target.value)} /></label>
          <ConnectionForm title="Connection" dbTypes={SOURCE_DB_TYPES} check={null} onChange={ignoreChange} metadataOnly savedLabel={label} onSaved={added} />
        </>}
        {modal?.kind === "details" && <>
          <dl className="connections-dialog__details">{Object.entries({ Name: modal.connection.label, Engine: connectionEngineNames[modal.connection.type], Host: modal.connection.host, Port: modal.connection.port ?? "Default", Database: modal.connection.database || modal.connection.service || "Not specified", Account: modal.connection.username, Authentication: modal.connection.auth_method === "entra" ? "Entra ID" : "Password", TLS: modal.connection.ssl ? "Enabled" : "Disabled" }).map(([title, value]) => <div key={title}><dt>{title}</dt><dd>{value}</dd></div>)}</dl>
          <div className="connections-dialog__actions"><button type="button" className="btn btn--secondary btn--sm" onClick={() => { setLabel(modal.connection.label); setModal({ ...modal, kind: "rename" }); }}><Pencil size={16} />Rename</button></div>
        </>}
        {modal?.kind === "rename" && <form onSubmit={async event => { event.preventDefault(); if (!label.trim()) return; try { await saveConnection({ ...modal.connection, label: label.trim() }); setModal(null); push("Connection renamed", "success"); } catch (reason) { push(String(reason), "error"); } }}>
          <label className="field"><span className="field__label">Display name</span><input className="input" required maxLength={40} value={label} onChange={event => setLabel(event.target.value)} /></label>
          <div className="connections-dialog__actions"><button type="submit" className="btn btn--primary btn--sm" disabled={!label.trim()}>Save name</button></div>
        </form>}
        {modal?.kind === "delete" && <>
          <p>Delete the saved {connectionEngineNames[modal.connection.type]} profile for <strong>{modal.connection.host}</strong>?</p>
          {(matchesConnection(modal.connection, source) || matchesConnection(modal.connection, target)) && <p>The selected connection form will be cleared.</p>}
          <p>The database will not be deleted.</p>
          <div className="connections-dialog__actions"><button type="button" className="btn btn--secondary btn--sm" autoFocus onClick={() => setModal(null)}>Cancel</button><button type="button" className="btn btn--danger btn--sm" onClick={async () => { try { await deleteConnection(modal.connection.id); onDelete(modal.connection); setModal(null); addButton.current?.focus(); push("Saved connection deleted", "success"); } catch (reason) { push(String(reason), "error"); } }}><Trash2 size={16} />Delete connection</button></div>
        </>}
      </dialog>
    </section>
  );
}