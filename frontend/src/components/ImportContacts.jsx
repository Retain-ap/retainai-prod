import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FaCloudUploadAlt, FaGoogle, FaHistory, FaUndo } from "react-icons/fa";
import { apiUrl } from "../apiBase";
import "./product-system.css";
import "./ImportContacts.css";
import SquareBookingsCard from "./SquareBookingsCard";

export const FIELDS = [
  ["name", "Full name"], ["first_name", "First name"], ["last_name", "Last name"],
  ["email", "Email"], ["phone", "Phone / WhatsApp"], ["company", "Company"],
  ["title", "Job title"], ["notes", "Notes"], ["birthday", "Birthday"],
];

// Where each export lives. Menus move between app versions, so the steps stay short.
export const SOURCES = [
  { key: "apple", label: "iPhone, Mac or iCloud", file: ".vcf", steps: "iPhone: Contacts → Lists → touch and hold a list → Export, then save to Files. Mac: Contacts → select contacts → File → Export → Export vCard. iCloud.com: Contacts → select contacts → ⋯ → Export vCard." },
  { key: "android", label: "Android or WhatsApp", file: ".vcf", steps: "WhatsApp uses your phone's address book and has no contact export of its own. Export your phone contacts (Android: Contacts → Settings → Export → .vcf file), or share one contact card from WhatsApp as a .vcf. Chats and messages are never imported." },
  { key: "google", label: "Google Contacts", file: ".csv or .vcf", steps: "contacts.google.com → Export → Google CSV or vCard. Or connect Google below to import directly." },
  { key: "outlook", label: "Outlook", file: ".csv or .vcf", steps: "Outlook.com: People → Manage contacts → Export contacts. Outlook desktop: File → Open & Export → Import/Export → Export to a file → CSV." },
  { key: "hubspot", label: "HubSpot", file: ".csv", steps: "Contacts → choose a view → Export → CSV." },
  { key: "salesforce", label: "Salesforce", file: ".csv", steps: "Run a Contacts report → Export → Details only → CSV. Admins can also use Data Export." },
  { key: "pipedrive", label: "Pipedrive", file: ".csv", steps: "Contacts → People → ⋯ → Export filter results → CSV." },
  { key: "zoho", label: "Zoho CRM", file: ".csv", steps: "Setup → Data Administration → Export → Contacts → CSV." },
  { key: "other", label: "Any spreadsheet", file: ".csv", steps: "Save the sheet as CSV with column names in the first row. Each contact needs an email or a phone number." },
];

const STATUS = {
  imported: ["New", "active"], updated: ["Update", "trial"], merged: ["Fill blanks", "trial"],
  skipped: ["Skip", "import-skip"], invalid: ["Needs fixing", "past_due"],
};
const FILTERS = [["all", "All"], ["ready", "Will import"], ["skipped", "Skipped"], ["invalid", "Needs fixing"]];
const REASONS = {
  not_selected: "Not selected", duplicate_in_file: "Appears earlier in this file",
  already_in_crm: "Already in RetainAI", identity_conflict: "Email and phone belong to different contacts", missing_email_or_phone: "No valid email or phone",
  invalid_email: "Email is not valid", invalid_phone: "Phone number is not valid",
};
const ROW_LIMIT = 200;

async function request(path, options = {}, userEmail = "") {
  const response = await fetch(apiUrl(path), {
    credentials: "include", ...options,
    headers: { Accept: "application/json", ...(userEmail ? { "X-User-Email": userEmail } : {}), ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Import request failed (${response.status})`);
  return data;
}

function rowName(row, outcome, mapping) {
  const raw = row?.raw || {};
  const pick = (field) => (mapping[field] ? String(raw[mapping[field]] || "").trim() : "");
  return outcome?.contact?.name || pick("name") || [pick("first_name"), pick("last_name")].filter(Boolean).join(" ") || "—";
}

function reasonText(reasons, code) {
  return code ? (reasons?.[code] || REASONS[code] || code) : "";
}

export default function ImportContacts({ user, focusGoogle = false }) {
  const userEmail = useMemo(() => String(user?.org_id || user?.email || "").toLowerCase(), [user]);
  const inputRef = useRef(null);
  const popupRef = useRef(null);
  const googleCardRef = useRef(null);
  const planSeq = useRef(0);
  const dirty = useRef(false);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [guide, setGuide] = useState("apple");
  const [preview, setPreview] = useState(null);
  const [rows, setRows] = useState([]);
  const [mapping, setMapping] = useState({});
  const [countryCode, setCountryCode] = useState("+1");
  const [duplicateMode, setDuplicateMode] = useState("skip");
  const [tag, setTag] = useState("Imported");
  const [plan, setPlan] = useState(null);
  const [planning, setPlanning] = useState(false);
  const [filter, setFilter] = useState("all");
  const [result, setResult] = useState(null);
  const [googleResult, setGoogleResult] = useState(null);
  const [undoResult, setUndoResult] = useState(null);
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
    if (!focusGoogle) return undefined;
    const timer = window.setTimeout(() => {
      googleCardRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
      googleCardRef.current?.focus({ preventScroll: true });
    }, 100);
    return () => window.clearTimeout(timer);
  }, [focusGoogle]);

  const hasChannel = Boolean(mapping.email || mapping.phone);
  const payload = useCallback((extra = {}) => ({
    rows, mapping, country_code: countryCode, duplicate_mode: duplicateMode, tag,
    source: preview?.format || "csv", file_name: file?.name, ...extra,
  }), [rows, mapping, countryCode, duplicateMode, tag, preview, file]);

  // Recount on the server whenever the mapping, options or selection change,
  // so the review always shows exactly what the import will do.
  useEffect(() => {
    if (!preview || !dirty.current) return undefined;
    const seq = ++planSeq.current;
    if (!hasChannel) { setPlan(null); setPlanning(false); return undefined; }
    setPlanning(true);
    const timer = window.setTimeout(async () => {
      try {
        const data = await request("import/file/commit", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload({ dry_run: true })),
        }, userEmail);
        if (seq === planSeq.current) setPlan({ summary: data.summary, outcomes: data.outcomes || [] });
      } catch (err) {
        if (seq === planSeq.current) setError(err.message);
      } finally {
        if (seq === planSeq.current) setPlanning(false);
      }
    }, 400);
    return () => window.clearTimeout(timer);
  }, [preview, hasChannel, payload, userEmail]);

  function edited(setter) {
    return (value) => { dirty.current = true; setter(value); };
  }

  function clearPreview() {
    planSeq.current += 1;
    dirty.current = false;
    setPreview(null); setRows([]); setPlan(null); setPlanning(false); setFile(null);
  }

  async function createPreview(selected) {
    if (!selected) return;
    clearPreview();
    setFile(selected); setBusy("preview"); setError(""); setResult(null); setGoogleResult(null); setFilter("all");
    try {
      const form = new FormData(); form.append("file", selected);
      const data = await request("import/file/preview", { method: "POST", body: form }, userEmail);
      // The server preview uses these defaults; later edits trigger a recount.
      setCountryCode("+1"); setDuplicateMode("skip");
      setPreview(data); setRows(data.rows || []); setMapping(data.mapping || {});
      setPlan({ summary: data.summary, outcomes: data.outcomes || [] });
    } catch (err) {
      setFile(null); setError(err.message);
    } finally {
      setBusy("");
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function commit() {
    setBusy("commit"); setError("");
    try {
      const data = await request("import/file/commit", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()),
      }, userEmail);
      const problems = (data.outcomes || [])
        .filter((item) => item.status === "invalid" || (item.status === "skipped" && item.reason !== "not_selected") || (item.reason && item.status !== "skipped"))
        .map((item) => ({ ...item, name: rowName(rows[item.index], item, mapping) }));
      setResult({ summary: data.summary || {}, problems, reasons: preview?.reasons });
      clearPreview();
      await refresh();
      window.dispatchEvent(new Event("leads:changed"));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  async function undo(id) {
    if (!window.confirm("Undo this import? Contacts it added are removed and contacts it changed go back to how they were. Contacts edited since the import are kept as they are.")) return;
    setBusy(`undo:${id}`); setError(""); setUndoResult(null);
    try {
      const data = await request(`import/${encodeURIComponent(id)}/undo`, { method: "POST" }, userEmail);
      setUndoResult(data);
      await refresh(); window.dispatchEvent(new Event("leads:changed"));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  function connectGoogle() {
    const redirect = `${window.location.origin}/app/import`;
    popupRef.current = window.open(apiUrl(`google/authorize?userEmail=${encodeURIComponent(userEmail)}&redirect=${encodeURIComponent(redirect)}`), "google_contacts", "width=540,height=700");
    const timer = setInterval(() => { if (!popupRef.current || popupRef.current.closed) { clearInterval(timer); refresh(); } }, 800);
  }

  async function importGoogle() {
    setBusy("google"); setError(""); setResult(null);
    try {
      const data = await request("google/import-now", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ userEmail }) }, userEmail);
      setGoogleResult(data.summary || {}); await refresh(); window.dispatchEvent(new Event("leads:changed"));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  async function disconnectGoogle() {
    setBusy("google-disconnect"); setError("");
    try {
      await request("google/disconnect", { method: "POST" }, userEmail);
      setGoogle((current) => ({ ...(current || {}), google_connected: false, has_refresh_token: false, sync_token_present: false }));
    } catch (err) { setError(err.message); } finally { setBusy(""); }
  }

  const outcomes = plan?.outcomes || [];
  const summary = plan?.summary || {};
  const ready = (summary.imported || 0) + (summary.updated || 0) + (summary.merged || 0);
  const selectedCount = rows.filter((row) => row.selected !== false).length;
  const visible = rows
    .map((row, index) => ({ row, index, outcome: outcomes[index] }))
    .filter(({ outcome }) => {
      const status = outcome?.status;
      if (filter === "ready") return ["imported", "updated", "merged"].includes(status);
      if (filter === "skipped") return status === "skipped";
      if (filter === "invalid") return status === "invalid";
      return true;
    });
  const source = SOURCES.find((item) => item.key === guide) || SOURCES[0];

  return (
    <div className="product-page import-workspace">
      <header className="product-hero"><div><div className="product-eyebrow">Customer data</div><h1>Import contacts</h1><p>Bring contacts from your phone, email or another CRM. You review every row before anything is saved, and nothing is sent to the people you import.</p></div></header>
      {error && <div className="product-alert danger" role="alert">{error}</div>}
      {undoResult && <div className="product-alert success import-result" role="status">
        <div><strong>Import undone.</strong> Removed {undoResult.removed_contacts || 0}, restored {undoResult.restored_contacts || 0}.{undoResult.kept_contacts ? ` ${undoResult.kept_contacts} contact${undoResult.kept_contacts === 1 ? " was" : "s were"} changed after the import and kept as ${undoResult.kept_contacts === 1 ? "it is" : "they are"}.` : ""}</div>
        {undoResult.conflicts?.length > 0 && <details><summary>Kept contacts ({undoResult.conflicts.length})</summary><ul>{undoResult.conflicts.map((item) => <li key={item.id}>{item.name || "Unnamed contact"}</li>)}</ul></details>}
        <button type="button" className="product-button" onClick={() => setUndoResult(null)}>Dismiss</button>
      </div>}
      {googleResult && <div className="product-alert success" role="status"><strong>Google import complete.</strong> Added {googleResult.imported || 0}, updated {googleResult.merged || 0}, skipped {googleResult.skipped || 0}.</div>}
      {result && <ImportResult result={result} onClose={() => setResult(null)} />}

      <div className="import-grid">
        <section className="product-card">
          <div className="product-card-header"><div><h2>Upload a contact file</h2><p className="product-card-copy">CSV or vCard (.vcf), up to 5 MB and 5,000 contacts.</p></div></div>
          <button type="button" className={`import-dropzone ${dragging ? "dragging" : ""}`} disabled={busy === "preview"} onClick={() => inputRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); createPreview(event.dataTransfer.files?.[0]); }}>
            <FaCloudUploadAlt aria-hidden="true" /><strong>{busy === "preview" ? "Reading file…" : file?.name || "Drop a .csv or .vcf file here"}</strong><span>or tap to choose a file</span>
          </button>
          <input ref={inputRef} hidden type="file" data-testid="import-file" accept=".csv,.tsv,.txt,.vcf,.vcard,text/csv,text/vcard,text/x-vcard" onChange={(event) => createPreview(event.target.files?.[0])} />
        </section>

        <section className="product-card">
          <div className="product-card-header"><div><h2>Where to get your file</h2><p className="product-card-copy">Pick where your contacts are now.</p></div></div>
          <div className="import-sources" role="group" aria-label="Contact sources">
            {SOURCES.map((item) => <button key={item.key} type="button" className={`import-source ${guide === item.key ? "active" : ""}`} aria-pressed={guide === item.key} onClick={() => setGuide(item.key)}>{item.label}</button>)}
          </div>
          <div className="import-guide" aria-live="polite"><strong>{source.label} <small>{source.file}</small></strong><p>{source.steps}</p></div>
        </section>
      </div>

      {preview && <section className="product-card import-preview" aria-label="Review import">
        <div className="product-card-header"><div>
          <h2>Review {file?.name || "import"}</h2>
          <p className="product-card-copy">Detected: {preview.preset?.label || (preview.format === "vcard" ? "vCard" : "CSV")} · {preview.total_rows} contacts{preview.truncated ? ` (only the first ${preview.max_rows} are imported)` : ""}</p>
        </div></div>

        <div className="import-summary ra-keep-grid" aria-live="polite" data-testid="import-summary">
          {[["New", summary.imported], ["Update", (summary.updated || 0) + (summary.merged || 0)], ["Skip", summary.skipped], ["Needs fixing", summary.invalid]].map(([label, value]) => <div key={label}><strong>{planning ? "…" : value || 0}</strong><span>{label}</span></div>)}
        </div>

        <h3 className="import-subhead">Match columns</h3>
        <div className="mapping-grid">{FIELDS.map(([key, label]) => <label key={key}>{label}<select className="product-input" value={mapping[key] || ""} onChange={(event) => edited(setMapping)({ ...mapping, [key]: event.target.value })}><option value="">Not imported</option>{preview.headers.map((header) => <option key={header} value={header}>{header}</option>)}</select></label>)}</div>
        {!hasChannel && <div className="product-alert danger" role="alert">Match an Email or Phone column. Every contact needs one so it can be matched and reached.</div>}

        <div className="import-options">
          <label>Country code for local numbers<input className="product-input" value={countryCode} inputMode="tel" onChange={(event) => edited(setCountryCode)(event.target.value)} /></label>
          <label>If a contact already exists<select className="product-input" value={duplicateMode} onChange={(event) => edited(setDuplicateMode)(event.target.value)}><option value="skip">Skip it</option><option value="merge">Fill in its blank fields</option><option value="update">Replace with file values</option></select></label>
          <label>Tag imported contacts<input className="product-input" value={tag} maxLength={80} onChange={(event) => setTag(event.target.value)} /></label>
        </div>
        <div className="product-alert import-consent" role="note" data-testid="import-consent">
          <strong>Email consent</strong>
          <p>New contacts from this file are not marked as agreeing to email. RetainAI sends them no automated emails (follow-ups or birthday greetings) until you confirm consent on their profile. Existing contacts this import updates keep their current consent and automations. Nothing is sent when you import.</p>
        </div>

        <div className="import-filters" role="group" aria-label="Filter rows">
          {FILTERS.map(([key, label]) => <button key={key} type="button" className={`import-source ${filter === key ? "active" : ""}`} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}
        </div>
        <div className="owner-table-wrap"><table className="owner-table import-table">
          <thead><tr>
            <th><input type="checkbox" aria-label="Select all rows" checked={rows.length > 0 && selectedCount === rows.length} onChange={(event) => edited(setRows)(rows.map((row) => ({ ...row, selected: event.target.checked })))} /></th>
            <th>Name</th><th>Email</th><th>Phone</th><th>Result</th>
          </tr></thead>
          <tbody>{visible.slice(0, ROW_LIMIT).map(({ row, index, outcome }) => {
            const [label, tone] = STATUS[outcome?.status] || ["—", "import-skip"];
            const raw = row.raw || {};
            return <tr key={index}>
              <td><input type="checkbox" aria-label={`Import row ${index + 1}`} checked={row.selected !== false} onChange={() => edited(setRows)(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, selected: item.selected === false } : item)))} /></td>
              <td>{rowName(row, outcome, mapping)}</td>
              <td>{outcome?.contact?.email || (mapping.email && raw[mapping.email]) || "—"}</td>
              <td>{outcome?.contact?.phone || (mapping.phone && raw[mapping.phone]) || "—"}</td>
              <td><span className={`status-pill ${tone}`}>{label}</span>{outcome?.reason && <small className="import-reason">{reasonText(preview.reasons, outcome.reason)}</small>}</td>
            </tr>;
          })}</tbody>
        </table></div>
        {visible.length > ROW_LIMIT && <p className="product-card-copy">Showing the first {ROW_LIMIT} of {visible.length} rows. Every selected row is processed.</p>}
        {!visible.length && <p className="product-card-copy">No rows match this filter.</p>}
        <div className="owner-account-creator-actions">
          <button type="button" className="product-button" onClick={clearPreview}>Cancel</button>
          <button type="button" className="product-button primary" disabled={!hasChannel || !ready || planning || Boolean(busy)} onClick={commit}>{busy === "commit" ? "Importing…" : `Import ${ready} contact${ready === 1 ? "" : "s"}`}</button>
        </div>
      </section>}

      <section ref={googleCardRef} className={`product-card ${focusGoogle ? "google-import-focus" : ""}`} tabIndex="-1">
        <div className="product-card-header"><div><h2>Google Contacts</h2><p className="product-card-copy">Import directly from your connected Google account.</p></div><FaGoogle aria-hidden="true" /></div>
        <div className="integration-summary"><span className={`status-pill ${google?.google_connected ? "active" : "pending_payment"}`}>{google?.google_connected ? "Connected" : "Not connected"}</span><strong>{google?.leads_count || 0} contacts in RetainAI</strong></div>
        <div className="google-import-actions">
          <button type="button" className="product-button primary" onClick={google?.google_connected ? importGoogle : connectGoogle} disabled={Boolean(busy)}>{busy === "google" ? "Importing…" : google?.google_connected ? "Import latest contacts" : "Connect Google"}</button>
          {google?.google_connected ? <button type="button" className="product-button danger" onClick={disconnectGoogle} disabled={Boolean(busy)}>{busy === "google-disconnect" ? "Disconnecting…" : "Disconnect"}</button> : null}
        </div>
      </section>

      <SquareBookingsCard />

      <section className="product-card">
        <div className="product-card-header"><div><h2>Recent imports</h2><p className="product-card-copy">Undo removes the contacts a file import added and restores the ones it changed. Contacts edited since then are kept.</p></div><FaHistory aria-hidden="true" /></div>
        <div className="insight-list">{history.map((item) => <div className="insight-row" key={item.id}><div className="insight-row-main"><strong>{item.label}</strong><small>{new Date(item.created_at * 1000).toLocaleString()} · {item.summary?.imported || 0} added · {(item.summary?.updated || 0) + (item.summary?.merged || 0)} updated</small></div>{item.undo_available === false ? <small className="import-reason">Undo isn't available for imports made before safe undo</small> : <button type="button" className="product-button" onClick={() => undo(item.id)} disabled={Boolean(busy)}><FaUndo aria-hidden="true" /> Undo</button>}</div>)}{!history.length && <div className="owner-empty-state"><strong>No imports yet</strong><small>Your import report and undo option will appear here.</small></div>}</div>
      </section>
    </div>
  );
}

function ImportResult({ result, onClose }) {
  const { summary = {}, problems = [], reasons } = result;
  const updated = (summary.updated || 0) + (summary.merged || 0);
  return (
    <section className="product-alert success import-result" role="status">
      <div>
        <strong>Import finished.</strong> Added {summary.imported || 0}, updated {updated}, skipped {summary.skipped || 0}, could not import {summary.invalid || 0}.
        {summary.warnings ? ` ${summary.warnings} saved without a value that was not valid.` : ""} Nothing was sent to these contacts.
      </div>
      {problems.length > 0 && <details>
        <summary>Rows to check ({problems.length})</summary>
        <ul>{problems.slice(0, 100).map((item) => <li key={item.index}>Contact {item.index + 1}: {item.name} — {reasonText(reasons, item.reason) || item.status}</li>)}</ul>
        {problems.length > 100 && <p>Showing the first 100.</p>}
      </details>}
      <button type="button" className="product-button" onClick={onClose}>Dismiss</button>
    </section>
  );
}
