import React, { useCallback, useEffect, useMemo, useState } from "react";
import { FaSyncAlt } from "react-icons/fa";
import { SiWhatsapp } from "react-icons/si";
import { apiUrl } from "../apiBase";

export default function WhatsAppHealthCard() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(apiUrl("whatsapp/health"), {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || `Request failed (${response.status})`);
      setHealth(data);
    } catch (err) {
      setHealth(null);
      setError(err?.message || "Could not check WhatsApp status.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const connected = useMemo(
    () => Boolean(health?.has_token && health?.has_phone_id && health?.has_waba_id),
    [health]
  );

  return (
    <article className={`account-card account-card-whatsapp${connected ? " is-connected" : ""}`}>
      <div className="account-card-top">
        <div className="account-brand-icon whatsapp" aria-hidden="true">
          <SiWhatsapp />
        </div>
        <span className={`account-status-badge ${connected ? "connected" : "attention"}`}>
          <span />
          {loading ? "Checking" : connected ? "Connected" : "Action required"}
        </span>
      </div>

      <div className="account-card-copy">
        <h3>WhatsApp Business</h3>
        <p>Send approved templates and continue conversations inside RetainAI.</p>
      </div>

      <div className="account-card-content">
        <div className="account-check-list">
          <div className={health?.has_token ? "ready" : "missing"}>
            <span /> API access token
          </div>
          <div className={health?.has_phone_id ? "ready" : "missing"}>
            <span /> Phone number ID
          </div>
          <div className={health?.has_waba_id ? "ready" : "missing"}>
            <span /> Business account ID
          </div>
        </div>
        {health?.default_template ? (
          <div className="account-id-row">
            <span>Default template</span>
            <code>{health.default_template}</code>
          </div>
        ) : null}
        {error ? <div className="account-inline-message error">{error}</div> : null}
      </div>

      <div className="account-card-actions">
        <button className="account-primary-btn whatsapp" onClick={refresh} disabled={loading}>
          <FaSyncAlt className={loading ? "account-spin" : ""} />
          {loading ? "Checking…" : "Refresh status"}
        </button>
      </div>
    </article>
  );
}
