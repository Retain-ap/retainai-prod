import React, { useState } from "react";
import { apiUrl } from "../apiBase";

export default function TrialCommandBar({ user }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const days = Number(user?.trialDaysRemaining || 0);
  const visible = !user?.platformOwner && (user?.trialActive || user?.billingRequired);
  if (!visible) return null;

  const openBilling = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(apiUrl("billing/checkout"), {
        method: "POST",
        credentials: "include",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.url) {
        throw new Error(data.error || "Could not open billing.");
      }
      window.location.assign(data.url);
    } catch (error) {
      setMessage(error.message);
      setBusy(false);
    }
  };

  return (
    <aside className={`trial-command-bar ${days <= 3 ? "urgent" : ""}`}>
      <div>
        <strong>
          {user?.billingRequired
            ? "Your workspace is ready to reactivate"
            : `${days} day${days === 1 ? "" : "s"} left in your RetainAI trial`}
        </strong>
        <span>
          {user?.billingRequired
            ? "Your customer data remains protected."
            : "Keep every relationship insight, playbook, and follow-up working."}
        </span>
        {message && <small>{message}</small>}
      </div>
      <button type="button" onClick={openBilling} disabled={busy}>
        {busy ? "Opening secure billing…" : "Choose plan"}
      </button>
    </aside>
  );
}
