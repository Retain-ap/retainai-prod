import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "../apiBase";

async function readPreference(response) {
  if (!response.ok) throw new Error("Preference request failed");
  const data = await response.json();
  const value = data?.preferences?.lead_reminder_emails;
  if (typeof value !== "boolean") throw new Error("Invalid preference response");
  return value;
}

export default function LeadReminderEmailSetting({ ownerEmail }) {
  const normalizedOwnerEmail = String(ownerEmail || "").trim().toLowerCase();
  const [enabled, setEnabled] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [message, setMessage] = useState("");
  const requestId = useRef(0);
  const controller = useRef(null);
  const pending = useRef(false);

  const cancelPendingRequest = useCallback(() => {
    ++requestId.current;
    controller.current?.abort();
  }, []);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    controller.current?.abort();
    controller.current = new AbortController();
    pending.current = true;
    setEnabled(null);
    setPhase("loading");
    setMessage("");
    if (!normalizedOwnerEmail) {
      pending.current = false;
      setPhase("error");
      setMessage("Sign in as the workspace owner to manage these email reminders.");
      return;
    }
    try {
      const value = await readPreference(await fetch(apiUrl("email/preferences"), {
        credentials: "include", signal: controller.current.signal,
        headers: { "X-User-Email": normalizedOwnerEmail },
      }));
      if (id !== requestId.current) return;
      setEnabled(value);
      setPhase("ready");
    } catch {
      if (id !== requestId.current) return;
      setPhase("error");
      setMessage("Email preferences could not be loaded. Try again.");
    } finally {
      if (id === requestId.current) pending.current = false;
    }
  }, [normalizedOwnerEmail]);

  useEffect(() => {
    load();
    return cancelPendingRequest;
  }, [load, cancelPendingRequest]);

  async function save(value) {
    if (!normalizedOwnerEmail || pending.current || phase !== "ready") return;
    pending.current = true;
    const id = ++requestId.current;
    controller.current = new AbortController();
    setPhase("saving");
    setMessage("");
    try {
      const confirmed = await readPreference(await fetch(apiUrl("email/preferences"), {
        method: "POST", credentials: "include", signal: controller.current.signal,
        headers: { "Content-Type": "application/json", "X-User-Email": normalizedOwnerEmail },
        body: JSON.stringify({ lead_reminder_emails: value }),
      }));
      if (id !== requestId.current) return;
      setEnabled(confirmed);
      setPhase("ready");
      setMessage(`Follow-up reminder emails turned ${confirmed ? "on" : "off"}.`);
    } catch {
      if (id !== requestId.current) return;
      setEnabled(null);
      setPhase("error");
      setMessage("We could not confirm the change. Reload the setting before trying again.");
    } finally {
      if (id === requestId.current) pending.current = false;
    }
  }

  return (
    <article className="account-card">
      <div className="account-card-copy">
        <h3>Follow-up reminder emails</h3>
        <p>Remind the workspace owner about leads needing attention. This email setting applies across devices.</p>
        <p>Reminders arrive during daytime hours, at most once a day. Unchanged follow-ups are reminded at most once a week.</p>
      </div>
      <div className="account-card-actions">
        <label>
          <input type="checkbox" checked={enabled === true} disabled={phase !== "ready"}
            onChange={(event) => save(event.target.checked)} />{" "}
          Email me when leads need attention
        </label>
      </div>
      {phase === "loading" && <p role="status">Loading email preference…</p>}
      {phase === "saving" && <p role="status">Saving email preference…</p>}
      {message && <p role={phase === "error" ? "alert" : "status"}>{message}</p>}
      {phase === "error" && normalizedOwnerEmail && <button type="button" className="account-secondary-btn" onClick={load}>Reload email preference</button>}
      <p>Security and sign-in emails continue. Customer email consent is managed separately.</p>
    </article>
  );
}
