import React, { useCallback, useEffect, useState } from "react";
import { apiUrl } from "../apiBase";

const CALLBACK_ERRORS = {
  expired: "The Calendly connection expired or was already used. Start again.",
  session_mismatch: "Finish connecting Calendly in the same browser and signed-in owner session that started it.",
  denied: "Calendly access was not granted.",
  failed: "Calendly could not be connected. Nothing was saved.",
  missing_scope: "Calendly didn't grant read access to scheduled events, so nothing was saved.",
  account_linked_elsewhere: "That Calendly account is already connected to another RetainAI workspace.",
  different_account: "Disconnect the current Calendly account before connecting a different one.",
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

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export default function CalendlyBookingsCard() {
  const [status, setStatus] = useState(null);
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("calendly") === "connected") return { ok: true, text: "Calendly is connected. Press Sync now to import bookings." };
    const code = params.get("calendly_error");
    return code ? { ok: false, text: CALLBACK_ERRORS[code] || CALLBACK_ERRORS.failed } : null;
  });

  const load = useCallback(async () => {
    try {
      setStatus(await call("calendly/status"));
    } catch (error) {
      if (error.status === 401 || error.status === 403) setHidden(true); // owner-only
      else setMessage({ ok: false, text: error.message });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function connect() {
    setBusy("connect");
    try {
      const { url } = await call("calendly/connect", { method: "POST" });
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
      const r = await call("calendly/sync", { method: "POST" });
      const notes = [];
      if (r.unmatched) notes.push(`${plural(r.unmatched, "invitee")} skipped because the email matches no single RetainAI contact`);
      if (r.cancelled) notes.push(`${r.cancelled} cancelled${r.rescheduled ? `, ${r.rescheduled} of them rescheduled` : ""}`);
      if (r.truncated) notes.push("only part of your Calendly history was read this time");
      setMessage({
        ok: true,
        text: `Read ${plural(r.events, "Calendly event")}: ${r.imported} new, ${r.updated} updated, ${r.unchanged} unchanged.${notes.length ? ` ${notes.join("; ")}.` : ""}`,
      });
      await load();
    } catch (error) {
      setMessage({ ok: false, text: error.message });
      await load();
    } finally {
      setBusy("");
    }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Calendly? Bookings already imported stay in RetainAI.")) return;
    setBusy("disconnect");
    try {
      const result = await call("calendly/disconnect", { method: "POST" });
      setMessage({ ok: result.revoked, text: result.revoked ? "Calendly was disconnected and RetainAI's access revoked." : result.message || "Calendly was disconnected." });
      await load();
    } catch (error) {
      setMessage({ ok: false, text: error.message });
    } finally {
      setBusy("");
    }
  }

  if (hidden) return null;
  return (
    <section className="product-card" aria-label="Calendly bookings">
      <div className="product-card-header">
        <div>
          <h2>Calendly (read-only)</h2>
          <p className="product-card-copy">
            Imports your Calendly bookings, cancellations and reschedules so rebooking and the Value Receipt use real visits.
            RetainAI reads your scheduled events and uses each invitee's email only to match contacts you already have. It never
            changes Calendly, adds contacts, records consent or messages anyone.
          </p>
        </div>
      </div>
      {message && <div className={`product-alert ${message.ok ? "success" : "danger"}`} role="status">{message.text}</div>}
      {!status && !message && <p className="product-card-copy">Checking Calendly…</p>}
      {status && !status.configured && !status.connected && !status.needs_reconnect && (
        <p className="product-card-copy" data-testid="calendly-unavailable">
          Not available yet: RetainAI's Calendly app hasn't been set up on this server, so Calendly can't be connected.
          You can still add visits in RetainAI.
        </p>
      )}
      {status && status.configured && !status.connected && !status.needs_reconnect && (
        <button type="button" className="product-button primary" onClick={connect} disabled={Boolean(busy)}>
          {busy === "connect" ? "Opening Calendly…" : "Connect Calendly"}
        </button>
      )}
      {status && (status.connected || status.needs_reconnect) && (
        <div className="google-import-actions">
          <p className="product-card-copy" style={{ width: "100%" }}>
            {status.needs_reconnect ? "Calendly no longer accepts RetainAI's access. Disconnect, then connect again to keep importing." : `Connected to Calendly user ${status.account}.`}
            {" "}Last sync: {when(status.last_sync?.at)}.
          </p>
          {status.connected && <button type="button" className="product-button primary" onClick={sync} disabled={Boolean(busy)}>{busy === "sync" ? "Syncing…" : "Sync now"}</button>}
          <button type="button" className="product-button danger" onClick={disconnect} disabled={Boolean(busy)}>{busy === "disconnect" ? "Disconnecting…" : "Disconnect"}</button>
        </div>
      )}
    </section>
  );
}
