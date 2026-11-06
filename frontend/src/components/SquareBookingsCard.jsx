import React, { useCallback, useEffect, useState } from "react";
import { apiUrl } from "../apiBase";

const CALLBACK_ERRORS = {
  expired: "The Square connection expired or was already used. Start again.",
  session_mismatch: "Finish connecting Square in the same signed-in owner session that started it.",
  denied: "Square access was not granted.",
  failed: "Square could not be connected. Nothing was saved.",
  merchant_linked_elsewhere: "That Square account is already connected to another RetainAI workspace.",
  different_merchant: "Disconnect the current Square account before connecting a different one.",
};

async function call(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function when(iso) {
  const date = iso ? new Date(iso) : null;
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : "never";
}

export default function SquareBookingsCard() {
  const [status, setStatus] = useState(null);
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("square") === "connected") return { ok: true, text: "Square is connected. Press Sync now to import bookings." };
    const code = params.get("square_error");
    return code ? { ok: false, text: CALLBACK_ERRORS[code] || CALLBACK_ERRORS.failed } : null;
  });

  const load = useCallback(async () => {
    try {
      setStatus(await call("square/status"));
    } catch (error) {
      if (error.status === 401 || error.status === 403) setHidden(true); // owner-only
      else setMessage({ ok: false, text: error.message });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function connect() {
    setBusy("connect");
    try {
      const { url } = await call("square/connect", { method: "POST" });
      window.location.assign(url);
    } catch (error) {
      setMessage({ ok: false, text: error.message });
      setBusy("");
    }
  }

  async function sync() {
    setBusy("sync");
    setMessage(null);
    try {
      const result = await call("square/sync", { method: "POST" });
      const parts = [`${result.imported} new`, `${result.updated} updated`, `${result.unchanged} unchanged`];
      const notes = [];
      if (result.unmatched) notes.push(`${result.unmatched} skipped because the Square customer matches no single RetainAI contact`);
      if (result.skipped) notes.push(`${result.skipped} pending bookings in the past skipped`);
      if (result.truncated || result.lookup_limit) notes.push("only part of your Square history was read this time");
      setMessage({ ok: true, text: `Read ${result.read} Square bookings: ${parts.join(", ")}.${notes.length ? ` ${notes.join("; ")}.` : ""}` });
      await load();
    } catch (error) {
      setMessage({ ok: false, text: error.message });
      await load();
    } finally {
      setBusy("");
    }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Square? Bookings already imported stay in RetainAI.")) return;
    setBusy("disconnect");
    try {
      const result = await call("square/disconnect", { method: "POST" });
      setMessage({ ok: result.revoked, text: result.revoked ? "Square was disconnected and RetainAI's access revoked." : result.message || "Square was disconnected." });
      await load();
    } catch (error) {
      setMessage({ ok: false, text: error.message });
    } finally {
      setBusy("");
    }
  }

  if (hidden) return null;
  return (
    <section className="product-card" aria-label="Square Appointments">
      <div className="product-card-header">
        <div>
          <h2>Square Appointments (read-only)</h2>
          <p className="product-card-copy">
            Imports your Square bookings so rebooking and the Value Receipt use real visits. RetainAI reads bookings and each
            booking customer's email or phone only to match contacts you already have. It never changes Square, adds contacts,
            records consent or messages anyone.
          </p>
        </div>
      </div>
      {message && <div className={`product-alert ${message.ok ? "success" : "danger"}`} role="status">{message.text}</div>}
      {!status && !message && <p className="product-card-copy">Checking Square…</p>}
      {status && !status.configured && !status.connected && (
        <p className="product-card-copy" data-testid="square-unavailable">
          Not available yet: RetainAI's Square app hasn't been set up on this server, so Square can't be connected.
        </p>
      )}
      {status && status.configured && !status.connected && !status.needs_reconnect && (
        <button type="button" className="product-button primary" onClick={connect} disabled={Boolean(busy)}>
          {busy === "connect" ? "Opening Square…" : "Connect Square"}
        </button>
      )}
      {status && (status.connected || status.needs_reconnect) && (
        <div className="google-import-actions">
          <p className="product-card-copy" style={{ width: "100%" }}>
            {status.needs_reconnect ? "Square no longer accepts RetainAI's access. Reconnect to keep importing." : `Connected to Square account ${status.merchant}.`}
            {" "}Last sync: {when(status.last_sync?.at)}.
          </p>
          {status.connected && <button type="button" className="product-button primary" onClick={sync} disabled={Boolean(busy)}>{busy === "sync" ? "Syncing…" : "Sync now"}</button>}
          {status.needs_reconnect && status.configured && <button type="button" className="product-button primary" onClick={async () => { await disconnect(); }} disabled={Boolean(busy)}>Disconnect, then reconnect</button>}
          {status.connected && <button type="button" className="product-button danger" onClick={disconnect} disabled={Boolean(busy)}>{busy === "disconnect" ? "Disconnecting…" : "Disconnect"}</button>}
        </div>
      )}
    </section>
  );
}
