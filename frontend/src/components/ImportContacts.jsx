// src/components/ImportContacts.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";

export default function ImportContacts({ user }) {
  // Use the SAME env var the rest of the app uses
  const API =
    process.env.REACT_APP_API_URL ||
    process.env.REACT_APP_API_BASE || // fallback if you had older builds
    "http://localhost:5000";

  // ---------- CSV state ----------
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  // ---------- Google state ----------
  const [gStatus, setGStatus] = useState(null);
  const [gBusy, setGBusy] = useState(false);
  const popupRef = useRef(null);

  const userEmail = useMemo(() => (user?.email || "").toLowerCase(), [user?.email]);

  // ---------- CSV handlers ----------
  async function handlePreview() {
    if (!file || !userEmail) return;
    setLoading(true);
    setResult(null);
    setPreview(null);
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API}/api/import/csv/preview`, {
      method: "POST",
      headers: { "X-User-Email": userEmail },
      body: form,
    });
    const data = await res.json();
    setPreview(data);
    setLoading(false);
  }

  function toggleRow(i) {
    const copy = {
      ...preview,
      rows: preview.rows.map((r, idx) =>
        idx === i ? { ...r, selected: r.selected === false ? true : (r.selected === true ? false : false) } : r
      ),
    };
    setPreview(copy);
  }

  function selectAll(val) {
    const copy = { ...preview, rows: preview.rows.map((r) => ({ ...r, selected: val })) };
    setPreview(copy);
  }

  async function handleImport() {
    if (!preview || !userEmail) return;
    setLoading(true);
    const payload = {
      rows: preview.rows.map((r) => ({ ...r, selected: r.selected !== false })),
    };
    const res = await fetch(`${API}/api/import/csv/commit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-User-Email": userEmail,
      },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    setResult(data?.summary || data);
    setLoading(false);
  }

  // ---------- Google: status ----------
  async function refreshGoogleStatus() {
    if (!userEmail) return;
    try {
      const res = await fetch(`${API}/api/google/status?userEmail=${encodeURIComponent(userEmail)}`);
      const data = await res.json();
      setGStatus(data);
    } catch (e) {
      setGStatus(null);
    }
  }

  useEffect(() => {
    refreshGoogleStatus();
    // listen for popup postMessage upon callback completion
    const onMsg = (e) => {
      if (e?.data && e.data.type === "google-import-complete") {
        refreshGoogleStatus();
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userEmail, API]);

  // ---------- Google: start OAuth in popup ----------
  function connectGoogle() {
    if (!userEmail) return;
    const redirectBack = `${window.location.origin}/app/import`; // land back here
    const url = `${API}/api/google/authorize?userEmail=${encodeURIComponent(
      userEmail
    )}&redirect=${encodeURIComponent(redirectBack)}`;

    // open popup
    const w = 520,
      h = 640;
    const left = window.screenX + (window.outerWidth - w) / 2;
    const top = window.screenY + (window.outerHeight - h) / 2;
    popupRef.current = window.open(
      url,
      "google_contacts_auth",
      `width=${w},height=${h},left=${left},top=${top}`
    );

    // optional: poll for close & refresh
    const iv = setInterval(() => {
      if (!popupRef.current || popupRef.current.closed) {
        clearInterval(iv);
        popupRef.current = null;
        refreshGoogleStatus();
      }
    }, 800);
  }

  // ---------- Google: import now with saved token ----------
  async function importFromGoogleNow() {
    if (!userEmail) return;
    setGBusy(true);
    try {
      const res = await fetch(`${API}/api/google/import-now`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userEmail }),
      });
      const data = await res.json();
      // surface a quick summary under the Google section
      setGStatus((prev) => ({
        ...(prev || {}),
        last_import_result: data,
      }));
      // You may also want to refresh your leads list elsewhere in your app
    } catch (e) {
      setGStatus((prev) => ({ ...(prev || {}), last_import_result: { status: "error" } }));
    } finally {
      setGBusy(false);
    }
  }

  return (
    <div style={{ padding: 16, color: "#e9edef" }}>
      <h2 style={{ marginBottom: 12 }}>Import Contacts</h2>

      {/* CSV Import */}
      <div style={{ background: "#232323", padding: 16, borderRadius: 12, marginBottom: 16 }}>
        <h3>1) CSV Import</h3>
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <button onClick={handlePreview} disabled={!file || loading} style={{ marginLeft: 8 }}>
          Preview
        </button>
      </div>

      {preview && (
        <div style={{ background: "#232323", padding: 16, borderRadius: 12, marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3>
              Preview ({preview.preview_count} of {preview.total_rows})
            </h3>
            <div>
              <button onClick={() => selectAll(true)} style={{ marginRight: 8 }}>
                Select All
              </button>
              <button onClick={() => selectAll(false)}>Deselect All</button>
            </div>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th></th>
                <th>Name</th>
                <th>Emails</th>
                <th>Phones</th>
                <th>Company</th>
                <th>Title</th>
                <th>Notes</th>
                <th>Dup</th>
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((r, i) => (
                <tr
                  key={i}
                  style={{
                    borderTop: "1px solid #2a3942",
                    background: r.duplicate ? "#1f1f1f" : "transparent",
                  }}
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={r.selected !== false}
                      onChange={() => toggleRow(i)}
                    />
                  </td>
                  <td>{r.name}</td>
                  <td>{(r.emails || []).join(", ")}</td>
                  <td>{(r.phones || []).join(", ")}</td>
                  <td>{r.company}</td>
                  <td>{r.title}</td>
                  <td
                    style={{
                      maxWidth: 240,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {r.notes}
                  </td>
                  <td>{r.duplicate ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={handleImport} disabled={loading} style={{ marginTop: 12 }}>
            Import Selected
          </button>
        </div>
      )}

      {result && (
        <div style={{ background: "#232323", padding: 16, borderRadius: 12 }}>
          <h3>Success</h3>
          <p>
            Imported: <b>{result.imported}</b> &nbsp; Merged: <b>{result.merged}</b> &nbsp; Skipped:{" "}
            <b>{result.skipped}</b>
          </p>
          <p>
            Total leads (after): <b>{result.total_after}</b>
          </p>
        </div>
      )}

      {/* Google Contacts */}
      <div style={{ background: "#232323", padding: 16, borderRadius: 12, marginTop: 16 }}>
        <h3>2) Google Contacts</h3>

        {!gStatus ? (
          <p>Checking Google status…</p>
        ) : gStatus.google_connected ? (
          <>
            <p>
              Connected ✅{gStatus.token_obtained_at ? (
                <>
                  &nbsp;•&nbsp;<span title="Token obtained at UNIX">{gStatus.token_obtained_at}</span>
                </>
              ) : null}
              {gStatus.sync_token_present ? " • Sync token saved" : ""}
              {typeof gStatus.leads_count === "number" ? ` • Leads: ${gStatus.leads_count}` : ""}
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={importFromGoogleNow} disabled={gBusy}>
                {gBusy ? "Importing…" : "Import Now"}
              </button>
              <button onClick={refreshGoogleStatus} disabled={gBusy}>
                Refresh Status
              </button>
            </div>
            {gStatus.last_import_result && (
              <div style={{ marginTop: 10, fontSize: 14 }}>
                Last import:{" "}
                <code style={{ background: "#1b1b1b", padding: "2px 6px", borderRadius: 6 }}>
                  {JSON.stringify(gStatus.last_import_result)}
                </code>
              </div>
            )}
          </>
        ) : (
          <>
            <p>Connect Google to import contacts.</p>
            <button onClick={connectGoogle} disabled={!userEmail}>
              Connect Google
            </button>
          </>
        )}
      </div>

      {(loading || gBusy) && <p style={{ marginTop: 8 }}>Working…</p>}
    </div>
  );
}
