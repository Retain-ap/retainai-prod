import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FaCloudUploadAlt, FaGoogle, FaHistory, FaUndo } from "react-icons/fa";
import { apiUrl } from "../apiBase";
import "./product-system.css";
import "./ImportContacts.css";

const FIELDS = [
  ["name", "Full name"], ["first_name", "First name"], ["last_name", "Last name"],
  ["email", "Email"], ["phone", "Phone / WhatsApp"], ["company", "Company"],
  ["title", "Job title"], ["notes", "Notes"],
];

async function request(path, options = {}, userEmail = "") {
  const response = await fetch(apiUrl(path), {
    credentials: "include", ...options,
    headers: { Accept: "application/json", ...(userEmail ? { "X-User-Email": userEmail } : {}), ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Import request failed (${response.status})`);
  return data;
}

export default function ImportContacts({ user, focusGoogle = false }) {
  const userEmail = useMemo(() => String(user?.org_id || user?.email || "").toLowerCase(), [user]);
  const inputRef = useRef(null);
  const popupRef = useRef(null);
  const googleCardRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [countryCode, setCountryCode] = useState("+1");
  const [duplicateMode, setDuplicateMode] = useState("skip");
  const [tag, setTag] = useState("CSV import");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [google, setGoogle] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!userEmail) return;
    const [historyData, googleData] = await Promise.all([
      request("import/history", {}, userEmail).catch(() => ({ imports: [] })),
      request(`google/status?userEmail=${encodeURIComponent(userEmail)}`, {}, userEmail).catch(() => null),
    ]);
    setHistory(historyData.imports || []);
    setGoogle(googleData);
  }, [userEmail]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!focusGoogle) return;
    const timer = window.setTimeout(() => {
      googleCardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      googleCardRef.current?.focus({ preventScroll: true });
    }, 100);
    return () => window.clearTimeout(timer);
  }, [focusGoogle]);

  async function createPreview(selected = file) {
    if (!selected) return;
    setFile(selected); setBusy("preview"); setError(""); setResult(null);
    try {
      const form = new FormData(); form.append("file", selected);
      const data = await request("import/csv/preview", { method: "POST", body: form }, userEmail);
      setPreview(data); setMapping(data.mapping || {});
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  async function commit() {
    setBusy("commit"); setError("");
    try {
      const data = await request("import/csv/commit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: preview.rows, mapping, country_code: countryCode, duplicate_mode: duplicateMode, tag, file_name: file?.name }),
      }, userEmail);
      setResult(data.summary); setPreview(null); setFile(null); await refresh();
      window.dispatchEvent(new Event("leads:changed"));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  async function undo(id) {
    if (!window.confirm("Undo this import and restore contacts to their previous state?")) return;
    setBusy(`undo:${id}`); setError("");
    try {
      await request(`import/${encodeURIComponent(id)}/undo`, { method: "POST" }, userEmail);
      await refresh(); window.dispatchEvent(new Event("leads:changed"));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  function connectGoogle() {
    const redirect = `${window.location.origin}/app/import`;
    popupRef.current = window.open(apiUrl(`google/authorize?userEmail=${encodeURIComponent(userEmail)}&redirect=${encodeURIComponent(redirect)}`), "google_contacts", "width=540,height=700");
    const timer = setInterval(() => { if (!popupRef.current || popupRef.current.closed) { clearInterval(timer); refresh(); } }, 800);
  }

  async function importGoogle() {
    setBusy("google"); setError("");
    try {
      const data = await request("google/import-now", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ userEmail }) }, userEmail);
      setResult(data); await refresh(); window.dispatchEvent(new Event("leads:changed"));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  async function disconnectGoogle() {
    setBusy("google-disconnect"); setError("");
    try {
      await request("google/disconnect", { method: "POST" }, userEmail);
      setGoogle((current) => ({ ...(current || {}), google_connected: false, has_refresh_token: false, sync_token_present: false }));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  const selectedCount = preview?.rows?.filter((row) => row.selected !== false).length || 0;
  return (
    <div className="product-page import-workspace">
      <header className="product-hero"><div><div className="product-eyebrow">Customer data</div><h1>Bring your customers with you</h1><p>Map, clean, preview, merge, and safely undo contact imports.</p></div></header>
      {error && <div className="product-alert danger">{error}</div>}
      {result && <div className="product-alert success"><strong>Import complete.</strong> Added {result.imported || 0}, updated {result.updated || result.merged || 0}, skipped {result.skipped || 0}.</div>}

      <div className="import-grid">
        <section className="product-card">
          <div className="product-card-header"><div><h2>CSV import</h2><p className="product-card-copy">Best for spreadsheets exported from another CRM.</p></div></div>
          <button type="button" className={`import-dropzone ${dragging ? "dragging" : ""}`} onClick={() => inputRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); createPreview(event.dataTransfer.files?.[0]); }}>
            <FaCloudUploadAlt /><strong>{file?.name || "Drop a CSV here"}</strong><span>or choose a file · maximum 5 MB</span>
          </button>
          <input ref={inputRef} hidden type="file" accept=".csv,text/csv" onChange={(event) => createPreview(event.target.files?.[0])} />
        </section>
        <section
          ref={googleCardRef}
          className={`product-card ${focusGoogle ? "google-import-focus" : ""}`}
          tabIndex="-1"
        >
          <div className="product-card-header"><div><h2>Google Contacts</h2><p className="product-card-copy">Securely import from your connected Google account.</p></div><FaGoogle /></div>
          <div className="integration-summary"><span className={`status-pill ${google?.google_connected ? "active" : "pending_payment"}`}>{google?.google_connected ? "Connected" : "Not connected"}</span><strong>{google?.leads_count || 0} contacts in RetainAI</strong></div>
          <div className="google-import-actions">
            <button className="product-button primary" onClick={google?.google_connected ? importGoogle : connectGoogle} disabled={Boolean(busy)}>{busy === "google" ? "Importing…" : google?.google_connected ? "Import latest contacts" : "Connect Google"}</button>
            {google?.google_connected ? <button className="product-button danger" onClick={disconnectGoogle} disabled={Boolean(busy)}>{busy === "google-disconnect" ? "Disconnecting…" : "Disconnect"}</button> : null}
          </div>
        </section>
      </div>

      {preview && <section className="product-card import-preview">
        <div className="product-card-header"><div><h2>Map and review</h2><p className="product-card-copy">{selectedCount} of {preview.rows.length} rows selected.</p></div></div>
        <div className="mapping-grid">{FIELDS.map(([key, label]) => <label key={key}>{label}<select className="product-input" value={mapping[key] || ""} onChange={(event) => setMapping((current) => ({ ...current, [key]: event.target.value }))}><option value="">Not imported</option>{preview.headers.map((header) => <option key={header}>{header}</option>)}</select></label>)}</div>
        <div className="import-options"><label>Default country code<input className="product-input" value={countryCode} onChange={(event) => setCountryCode(event.target.value)} /></label><label>Duplicates<select className="product-input" value={duplicateMode} onChange={(event) => setDuplicateMode(event.target.value)}><option value="skip">Skip existing</option><option value="update">Replace mapped fields</option><option value="merge">Fill missing fields</option></select></label><label>Tag imported contacts<input className="product-input" value={tag} onChange={(event) => setTag(event.target.value)} /></label></div>
        <div className="owner-table-wrap"><table className="owner-table"><thead><tr><th><input type="checkbox" checked={selectedCount === preview.rows.length} onChange={(event) => setPreview((current) => ({ ...current, rows: current.rows.map((row) => ({ ...row, selected: event.target.checked })) }))} /></th><th>Name</th><th>Email</th><th>Phone</th><th>Status</th></tr></thead><tbody>{preview.rows.slice(0, 100).map((row, index) => <tr key={index}><td><input type="checkbox" checked={row.selected !== false} onChange={() => setPreview((current) => ({ ...current, rows: current.rows.map((item, itemIndex) => itemIndex === index ? { ...item, selected: item.selected === false } : item) }))} /></td><td>{row.name || "—"}</td><td>{row.email || "—"}</td><td>{row.phone || "—"}</td><td><span className={`status-pill ${row.duplicate ? "pending_payment" : "active"}`}>{row.duplicate ? "Duplicate" : "New"}</span></td></tr>)}</tbody></table></div>
        {preview.rows.length > 100 && <p className="product-card-copy">Showing the first 100 rows. All {preview.rows.length} selected rows will be processed.</p>}
        <div className="owner-account-creator-actions"><button className="product-button" onClick={() => setPreview(null)}>Cancel</button><button className="product-button primary" disabled={!selectedCount || Boolean(busy)} onClick={commit}>{busy === "commit" ? "Importing…" : `Import ${selectedCount} contacts`}</button></div>
      </section>}

      <section className="product-card">
        <div className="product-card-header"><div><h2>Recent imports</h2><p className="product-card-copy">Undo restores the exact contact list from before that import.</p></div><FaHistory /></div>
        <div className="insight-list">{history.map((item) => <div className="insight-row" key={item.id}><div className="insight-row-main"><strong>{item.label}</strong><small>{new Date(item.created_at * 1000).toLocaleString()} · {item.summary?.imported || 0} added · {item.summary?.updated || item.summary?.merged || 0} updated</small></div><button className="product-button" onClick={() => undo(item.id)} disabled={Boolean(busy)}><FaUndo /> Undo</button></div>)}{!history.length && <div className="owner-empty-state"><strong>No imports yet</strong><small>Your import report and undo option will appear here.</small></div>}</div>
      </section>
    </div>
  );
}
